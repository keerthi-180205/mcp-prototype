"""Offline tests for the X (twitter-cli) collector. Output shape mirrors twitter_cli.serialization."""

import json

import pytest

import server.collection.collectors.x as xc
from server.collection.collectors.base import CollectorFatalError
from server.collection.collectors.x import XCollector
from server.collection.harvester import harvest_platform
from server.collection.models import CollectionLimits, PlatformProgress, PostCandidate, QueryPlan

PLAN = QueryPlan(topic="Asian Games 2026", keywords=["Asian Games 2026", "asian games"], hashtags=["asiangames2026"])


def _tweet(tid, screen="someone", uid="111", text="Asian Games 2026 is amazing", replies=10, likes=5):
    return {
        "id": str(tid), "text": text,
        "author": {"id": uid, "name": screen.title(), "screenName": screen, "profileImageUrl": "", "verified": False},
        "metrics": {"likes": likes, "retweets": 1, "replies": replies, "quotes": 0, "views": 1000, "bookmarks": 0},
        "createdAt": "Wed Oct 07 10:00:00 +0000 2026", "createdAtISO": "2026-10-07T10:00:00+00:00",
        "media": [], "urls": [], "isRetweet": False, "lang": "en",
    }


def _ok(items):
    return json.dumps({"ok": True, "schema_version": "1", "data": items})


@pytest.fixture
def fake_twitter(monkeypatch):
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "a" * 40)
    monkeypatch.setenv("TWITTER_CT0", "b" * 32)
    calls = []

    async def run(args, timeout=60.0, env=None, allow_nonzero=False):
        calls.append(args)
        if args[1] == "search":
            if args[2] == "asian games":
                return 0, _ok([_tweet(2, "fan", "222", replies=40)]), ""
            return 0, _ok([_tweet(1, "news_org", "100", replies=120), _tweet(3, "quiet", "333", replies=0),
                           _tweet(4, "off", "444", text="pasta recipe", replies=500)]), ""
        tid = args[2]
        replies = [_tweet(f"{tid}0{i}", f"replier{tid}{i}", f"9{tid}{i}", text=f"reply {i} to {tid}", likes=i) for i in range(60)]
        replies.append(_tweet(f"{tid}99", "news_org", "100", text="author thread continuation"))
        return 0, _ok([_tweet(tid, "news_org", "100", replies=120)] + replies), ""

    monkeypatch.setattr(xc, "run_cli", run)
    return XCollector(binary="/fake/twitter"), calls


@pytest.mark.asyncio
async def test_discover_candidates(fake_twitter):
    c, calls = fake_twitter
    found = await c.discover(PLAN, 40)
    ids = {p.post_id for p in found}
    assert {"1", "2", "4"} <= ids and "3" not in ids  # zero-reply tweets are never opened
    p = next(p for p in found if p.post_id == "1")
    assert p.url == "https://x.com/news_org/status/1" and p.comment_count == 120
    assert (p.author_username, p.author_id, p.published_at) == ("news_org", "100", "2026-10-07T10:00:00+00:00")
    searches = [a for a in calls if a[1] == "search"]
    assert any(a[2] == "#asiangames2026" for a in searches) and all("retweets" in a for a in searches)


@pytest.mark.asyncio
async def test_replies_become_comment_rows(fake_twitter):
    c, calls = fake_twitter
    post = PostCandidate(platform="x", post_id="1", url="https://x.com/news_org/status/1", author_username="news_org", author_id="100")
    rows = await c.fetch_post_comments(post, 50)
    assert len(rows) == 61  # focal tweet excluded; creator filtering is the cleaning step's job
    r = rows[3]
    assert (r.platform, r.username, r.user_id, r.likes, r.post_url) == (
        "x", "replier13", "913", 3, "https://x.com/news_org/status/1")
    assert r.created_at == "2026-10-07T10:00:00+00:00"
    assert next(a for a in calls if a[1] == "tweet")[-3:] == ["-n", "51", "--json"]


@pytest.mark.asyncio
async def test_harvest_drops_authors_own_replies_and_offtopic(fake_twitter):
    c, _ = fake_twitter
    prog = PlatformProgress(platform="x")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=50, max_posts=5), prog)
    assert prog.stop_reason == "target_reached" and len(rows) >= 50
    assert all(r.username != "news_org" for r in rows)  # thread continuation by the author removed
    assert "pasta" not in " ".join(r.comment for r in rows)


@pytest.mark.asyncio
async def test_expired_cookies_report_clear_fatal_error(monkeypatch):
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "a" * 40)
    monkeypatch.setenv("TWITTER_CT0", "b" * 32)

    async def run(args, **kw):
        err = {"ok": False, "schema_version": "1", "error": {"code": "not_authenticated", "message": "Cookie expired or invalid (HTTP 403)."}}
        return 1, json.dumps(err), ""

    monkeypatch.setattr(xc, "run_cli", run)
    c = XCollector(binary="/fake/twitter")
    with pytest.raises(CollectorFatalError, match="TWITTER_AUTH_TOKEN"):
        await c.fetch_post_comments(PostCandidate(platform="x", post_id="1", url="u"), 10)

    prog = PlatformProgress(platform="x")
    rows = await harvest_platform(c, PLAN, CollectionLimits(), prog)
    assert rows == [] and prog.status in ("done", "failed")  # search errors are swallowed -> no candidates


@pytest.mark.asyncio
async def test_fatal_during_harvest_marks_platform_failed(monkeypatch):
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "a" * 40)
    monkeypatch.setenv("TWITTER_CT0", "b" * 32)

    async def run(args, **kw):
        if args[1] == "search":
            return 0, _ok([_tweet(1, replies=50)]), ""
        return 1, json.dumps({"ok": False, "error": {"code": "not_authenticated", "message": "expired"}}), ""

    monkeypatch.setattr(xc, "run_cli", run)
    prog = PlatformProgress(platform="x")
    rows = await harvest_platform(XCollector(binary="/fake/twitter"), PLAN, CollectionLimits(), prog)
    assert rows == [] and prog.status == "failed" and "expired" in prog.error


def test_availability_needs_binary_and_both_cookies(monkeypatch):
    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    assert not XCollector(binary="/fake/twitter").is_available()
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "x")
    assert not XCollector(binary="/fake/twitter").is_available()
    monkeypatch.setenv("TWITTER_CT0", "y")
    assert XCollector(binary="/fake/twitter").is_available()
    monkeypatch.setattr(xc, "find_binary", lambda n: None)
    assert not XCollector().is_available() and "twitter-cli" in XCollector().unavailable_reason()


@pytest.mark.asyncio
async def test_social_provider_adapter(fake_twitter):
    from server.providers.social.x_twitter import XTwitterSocialProvider, _tweet_id

    c, _ = fake_twitter
    prov = XTwitterSocialProvider(collector=c)
    assert prov.provider_name == "twitter-cli" and prov.is_available()
    recs = await prov.search_content("Asian Games 2026", limit=5)
    assert recs and recs[0].platform == "x" and recs[0].engagement.comments
    assert _tweet_id("https://x.com/a/status/12345?s=20") == "12345"
    replies = await prov.get_comments("https://x.com/a/status/1", limit=5)
    assert len(replies) == 5 and replies[0].type == "reply"
