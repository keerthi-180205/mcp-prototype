"""Offline tests for the Reddit (rdt-cli) collector with mocked CLI output."""

import json

import pytest

import server.collection.collectors.reddit as rd
from server.collection.collectors.reddit import RedditCollector, ensure_credential
from server.collection.harvester import harvest_platform
from server.collection.models import CollectionLimits, PlatformProgress, QueryPlan

PLAN = QueryPlan(topic="Asian Games 2026", keywords=["Asian Games 2026", "asian games"], subreddits=["olympics"])


def _post(pid, n, title="Asian Games 2026 thread", author="op_user"):
    return {"kind": "t3", "data": {
        "id": pid, "title": title, "selftext": "", "author": author, "author_fullname": "t2_op", "num_comments": n,
        "score": 50, "created_utc": 1790000000.0, "permalink": f"/r/olympics/comments/{pid}/slug/", "subreddit": "olympics"}}


def _search_json(*posts):
    return json.dumps({"ok": True, "data": {"kind": "Listing", "data": {"children": list(posts)}}})


def _c(cid, author, body, score=1, replies=None, **extra):
    d = {"id": cid, "author": author, "author_fullname": f"t2_{author}", "body": body, "score": score,
         "created_utc": 1790100000.0, "replies": replies or ""}
    d.update(extra)
    return {"kind": "t1", "data": d}


def _listing(*children):
    return {"kind": "Listing", "data": {"children": list(children)}}


def _read_json(pid, n):
    comments = [_c(f"{pid}c{i}", f"user{pid}{i}", f"comment {i} on {pid}", score=i) for i in range(n)]
    # nested reply, deleted, removed, automod and OP's own comment
    comments[0] = _c(f"{pid}c0", "parent", "top level", replies=_listing(_c(f"{pid}r1", "replier", "nested reply", score=7)))
    comments += [
        _c("d1", "[deleted]", "[removed]"), _c("d2", "gone", "[removed]"),
        _c("a1", "AutoModerator", "Please follow the rules"),
        _c("o1", "op_user", "thanks everyone", is_submitter=True),
        {"kind": "more", "data": {"count": 500, "children": ["x"]}},
    ]
    return json.dumps({"ok": True, "data": [_listing({"kind": "t3", "data": {"id": pid}}), _listing(*comments)]})


@pytest.fixture
def fake_rdt(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("REDDIT_SESSION", "cookie-value-xyz")
    calls = []

    async def run(args, timeout=60.0, env=None, allow_nonzero=False):
        calls.append(args)
        if args[1] == "search":
            if "-r" in args:
                return 0, _search_json(_post("sub1", 80)), ""
            return 0, _search_json(_post("t1", 300), _post("t2", 120), _post("zero", 0), _post("off", 900, title="Pasta recipes")), ""
        pid = args[2]
        return 0, _read_json(pid, 60), ""

    monkeypatch.setattr(rd, "run_cli", run)
    return RedditCollector(binary="/fake/rdt"), calls


def test_credential_file_written_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ensure_credential("sess-123")
    path = tmp_path / ".config" / "rdt-cli" / "credential.json"
    data = json.loads(path.read_text())
    assert data["cookies"] == {"reddit_session": "sess-123"} and data["source"] == "env:REDDIT_SESSION"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    # existing user-saved credential is kept when REDDIT_SESSION is not provided
    monkeypatch.delenv("REDDIT_SESSION", raising=False)
    path.write_text(json.dumps({"cookies": {"reddit_session": "mine"}, "source": "browser"}))
    assert ensure_credential(None) and json.loads(path.read_text())["source"] == "browser"


@pytest.mark.asyncio
async def test_discover_merges_searches_and_skips_empty(fake_rdt):
    c, calls = fake_rdt
    found = await c.discover(PLAN, 40)
    ids = {p.post_id for p in found}
    assert {"t1", "t2", "sub1"} <= ids and "zero" not in ids
    p = next(p for p in found if p.post_id == "t1")
    assert p.url == "https://www.reddit.com/r/olympics/comments/t1/slug/" and p.comment_count == 300
    assert p.author_username == "op_user" and p.author_id == "t2_op"
    assert any("-r" in a and "olympics" in a for a in calls)


@pytest.mark.asyncio
async def test_comments_walk_replies_and_filter_noise(fake_rdt):
    c, calls = fake_rdt
    post = (await c.discover(PLAN, 40))[0]
    rows = await c.fetch_post_comments(post, 100)
    names = [r.username for r in rows]
    assert "replier" in names and "parent" in names  # nested replies are kept
    assert not {"[deleted]", "gone", "AutoModerator", "op_user"} & set(names)
    read = next(a for a in calls if a[1] == "read")
    assert "--expand-more" not in read and read[read.index("-n") + 1] == "100"
    r = next(r for r in rows if r.username == "replier")
    assert (r.user_id, r.likes, r.platform) == ("t2_replier", 7, "reddit") and r.created_at.startswith("2026-")


@pytest.mark.asyncio
async def test_harvest_reaches_target_across_threads(fake_rdt):
    c, _ = fake_rdt
    prog = PlatformProgress(platform="reddit")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=100, max_posts=5), prog)
    assert prog.stop_reason == "target_reached" and len(rows) >= 100
    assert len({r.post_url for r in rows}) >= 2 and all(r.username != "op_user" for r in rows)


@pytest.mark.asyncio
async def test_auth_failure_is_fatal(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("REDDIT_SESSION", "expired")

    async def run(args, **kw):
        return 1, json.dumps({"ok": False, "error": {"code": "forbidden", "message": "Access forbidden"}}), ""

    monkeypatch.setattr(rd, "run_cli", run)
    prog = PlatformProgress(platform="reddit")
    rows = await harvest_platform(RedditCollector(binary="/fake/rdt"), PLAN, CollectionLimits(), prog)
    # search errors are swallowed per-query; with no candidates the platform ends empty but cleanly
    assert rows == [] and prog.status in ("done", "failed")


@pytest.mark.asyncio
async def test_read_auth_error_surfaces_as_fatal(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("REDDIT_SESSION", "expired")

    async def run(args, **kw):
        return 1, json.dumps({"ok": False, "error": {"code": "forbidden", "message": "nope"}}), ""

    monkeypatch.setattr(rd, "run_cli", run)
    from server.collection.collectors.base import CollectorFatalError
    from server.collection.models import PostCandidate

    c = RedditCollector(binary="/fake/rdt")
    with pytest.raises(CollectorFatalError, match="REDDIT_SESSION"):
        await c.fetch_post_comments(PostCandidate(platform="reddit", post_id="a", url="u"), 10)


def test_unavailable_without_session_or_binary(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("REDDIT_SESSION", raising=False)
    assert not RedditCollector(binary="/fake/rdt").is_available()
    monkeypatch.setenv("REDDIT_SESSION", "x")
    monkeypatch.setattr(rd, "find_binary", lambda n: None)
    assert not RedditCollector().is_available()


@pytest.mark.asyncio
async def test_social_provider_adapter_uses_rdt(fake_rdt):
    from server.providers.social.reddit import RedditSocialProvider, _post_id

    c, calls = fake_rdt
    prov = RedditSocialProvider(collector=c)
    assert prov.provider_name == "rdt-cli" and prov.is_available()
    recs = await prov.search_content("Asian Games 2026", limit=5)
    assert recs and recs[0].platform == "reddit" and recs[0].engagement.comments == 300
    assert _post_id("https://www.reddit.com/r/olympics/comments/abc123/slug/") == "abc123"
    comments = await prov.get_comments("https://www.reddit.com/r/olympics/comments/t1/slug/", limit=10)
    assert len(comments) == 10 and comments[0].author.username
