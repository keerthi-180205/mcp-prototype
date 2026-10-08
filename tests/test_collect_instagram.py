"""Offline tests for the Instagram (Apify) collector: batching, mapping and hard caps."""

import pytest

from server.collection.collectors.base import CollectorFatalError
from server.collection.collectors.instagram import InstagramCollector
from server.collection.harvester import harvest_platform
from server.collection.models import CollectionLimits, PlatformProgress, QueryPlan
from server.providers.apify.client import ApifyAuthenticationError

PLAN = QueryPlan(topic="Asian Games 2026", keywords=["Asian Games 2026"], hashtags=["asiangames2026", "asiangames"])


def _post(code, comments, owner="creator", owner_id="900", caption="Great moments #asiangames2026"):
    return {
        "shortCode": code, "url": f"https://www.instagram.com/p/{code}/", "caption": caption,
        "commentsCount": comments, "likesCount": 10, "timestamp": "2026-10-08T10:00:00.000Z",
        "ownerUsername": owner, "ownerId": owner_id, "hashtags": ["asiangames2026"],
    }


def _comment(code, i, user=None, uid=None, replies=None):
    user = user or f"fan{code}{i}"
    return {
        "postUrl": f"https://www.instagram.com/p/{code}/", "id": f"{code}-{i}", "text": f"nice {code} {i}",
        "ownerUsername": user, "owner": {"username": user, "id": uid or f"id{code}{i}"},
        "timestamp": "2026-10-08T11:00:00.000Z", "likesCount": i, "replies": replies,
    }


class FakeProvider:
    def __init__(self, posts, per_post=5, fail=None):
        self.posts = posts
        self.per_post = per_post
        self.fail = fail
        self.search_calls = []
        self.comment_calls = []

    async def search_hashtags(self, hashtags, results_per_tag, max_items=None, max_total_charge_usd=None):
        self.search_calls.append((list(hashtags), results_per_tag, max_items, max_total_charge_usd))
        return self.posts

    async def get_comments_batch(self, post_urls, comments_per_post, max_items=None, max_total_charge_usd=None):
        if self.fail:
            raise self.fail
        self.comment_calls.append((list(post_urls), comments_per_post, max_items, max_total_charge_usd))
        out = []
        for url in post_urls:
            code = url.rstrip("/").rsplit("/", 1)[-1]
            out += [_comment(code, i) for i in range(self.per_post)]
        return out[:max_items] if max_items else out


@pytest.mark.asyncio
async def test_discovery_one_run_many_tags_skips_empty_posts():
    prov = FakeProvider([_post("A", 20), _post("B", 0), _post("C", 5), {"shortCode": "E", "error": "x"}])
    c = InstagramCollector(provider=prov)
    cands = await c.discover(PLAN, 40)
    assert [p.post_id for p in cands] == ["A", "C"]
    assert len(prov.search_calls) == 1 and prov.search_calls[0][0] == ["asiangames2026", "asiangames"]
    a = cands[0]
    assert (a.author_username, a.author_id, a.comment_count) == ("creator", "900", 20)
    assert "#asiangames2026" in a.text


@pytest.mark.asyncio
async def test_many_posts_are_fetched_in_a_single_actor_run():
    prov = FakeProvider([_post(f"P{i}", 10) for i in range(6)], per_post=10)
    c = InstagramCollector(provider=prov)
    prog = PlatformProgress(platform="instagram")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=55, max_posts=30), prog)
    assert len(prov.comment_calls) == 1 and len(prov.comment_calls[0][0]) == 6
    assert len(rows) == 60 and prog.posts_processed == 6
    r = rows[0]
    assert (r.platform, r.user_id.startswith("id"), r.post_url.startswith("https://www.instagram.com/p/")) == ("instagram", True, True)


@pytest.mark.asyncio
async def test_creator_comments_and_duplicates_removed():
    class P(FakeProvider):
        async def get_comments_batch(self, post_urls, comments_per_post, **kw):
            return [
                _comment("A", 1, user="creator", uid="900"),          # creator -> dropped
                _comment("A", 2, user="someone_else", uid="900"),     # same id as creator -> dropped
                _comment("A", 3, user="fan"), _comment("A", 3, user="fan"),  # duplicate
                {**_comment("A", 4), "text": "  "},                    # empty
                _comment("A", 5, replies=[{"ownerUsername": "replier", "owner": {"id": "r1"}, "text": "agree", "likesCount": 2}]),
            ]

    c = InstagramCollector(provider=P([_post("A", 6)]))
    prog = PlatformProgress(platform="instagram")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=100), prog)
    assert sorted(r.username for r in rows) == ["fan", "fanA5", "replier"]


@pytest.mark.asyncio
async def test_hard_cap_on_comments_limits_items_requested_and_stops():
    prov = FakeProvider([_post(f"P{i}", 100) for i in range(30)], per_post=50)
    c = InstagramCollector(provider=prov)
    prog = PlatformProgress(platform="instagram")
    limits = CollectionLimits(target_comments=5000, max_posts=100, apify_max_comments_per_query=60,
                              apify_max_cost_usd=100.0)
    rows = await harvest_platform(c, PLAN, limits, prog)
    # discovery is limited by the cap too; no call may ask for more items than the cap leaves
    assert all((call[2] or 0) <= 60 for call in prov.comment_calls + prov.search_calls)
    assert c.items_used <= 60 + 60  # discovery run + comment run, each individually capped
    assert prog.stop_reason == "budget_cap_reached" and len(rows) <= 60


@pytest.mark.asyncio
async def test_hard_cap_on_cost_stops_before_another_run():
    prov = FakeProvider([_post(f"P{i}", 100) for i in range(80)], per_post=5)
    c = InstagramCollector(provider=prov)
    c.cost_per_run, c.cost_per_item = 0.2, 0.0
    prog = PlatformProgress(platform="instagram")
    limits = CollectionLimits(target_comments=10_000, max_posts=500, apify_max_cost_usd=0.5)
    await harvest_platform(c, PLAN, limits, prog)
    assert c.runs == 2  # 1 discovery + 1 comments batch; third run (0.6 > 0.5) never starts
    assert c.spent_estimate <= 0.5 + 1e-9
    assert prog.stop_reason == "budget_cap_reached"
    # server-side cap is passed to every run and never exceeds the remaining budget
    assert all(call[3] <= 0.5 for call in prov.comment_calls + prov.search_calls)


@pytest.mark.asyncio
async def test_auth_error_is_fatal_and_reported():
    prov = FakeProvider([_post("A", 10)], fail=ApifyAuthenticationError("payment required"))
    prog = PlatformProgress(platform="instagram")
    rows = await harvest_platform(InstagramCollector(provider=prov), PLAN, CollectionLimits(), prog)
    assert rows == [] and prog.status == "failed" and "payment required" in prog.error


@pytest.mark.asyncio
async def test_skipped_without_token(monkeypatch):
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    prog = PlatformProgress(platform="instagram")
    await harvest_platform(InstagramCollector(token=""), PLAN, CollectionLimits(), prog)
    assert prog.status == "skipped" and "APIFY_API_TOKEN" in prog.error
