"""TrueScrape additions for the audience feature (post facts, profile grid, long comment paging) and the ledger
purge. Offline."""

import pytest

from server.collection.collectors.truescrape import (
    MAX_INSTAGRAM_PAGES, MIN_INSTAGRAM_PAGES, TrueScrapeBackend,
)
from server.collection.ledger import ProviderLedger
from server.collection.models import PostCandidate


@pytest.fixture
def ledger(tmp_path):
    return ProviderLedger(str(tmp_path / "ledger.db"))


class FakeTS:
    is_configured = True

    def __init__(self, handler):
        self.handler, self.calls = handler, []

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, dict(params or {})))
        return self.handler(endpoint, dict(params or {}), len(self.calls))


def envelope(items, cursor=None, has_more=False):
    return {"success": True, "data": {"items": items}, "pagination": {"cursor": cursor, "hasMore": has_more, "count": len(items)},
            "meta": {"creditsCharged": 1, "cached": False}}


def comment(i):
    return {"id": f"c{i}", "text": f"comment {i}", "authorId": f"id{i}", "authorHandle": f"user{i}", "likeCount": 0,
            "publishedAt": "2026-10-01T00:00:00Z"}


def ig_post(url="https://www.instagram.com/p/AAA/"):
    return PostCandidate(platform="instagram", post_id="AAA", url=url, comment_count=500)


# ---- long comment paging ------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_500_comment_target_pages_past_the_old_8_page_limit(ledger):
    PER_PAGE, TOTAL = 15, 900

    def handler(endpoint, params, n):
        start = (n - 1) * PER_PAGE
        items = [comment(i) for i in range(start, min(start + PER_PAGE, TOTAL))]
        return envelope(items, cursor=f"cur{n}", has_more=start + PER_PAGE < TOTAL)

    client = FakeTS(handler)
    rows = await TrueScrapeBackend("instagram", client=client, ledger=ledger).fetch_post_comments(ig_post(), 500)
    assert len(rows) == 500
    assert len(client.calls) == 34 > MIN_INSTAGRAM_PAGES              # ceil(500 / 15), stops as soon as it has enough
    assert client.calls[1][1]["cursor"] == "cur1"


@pytest.mark.asyncio
async def test_page_budget_has_a_hard_ceiling_and_small_requests_stay_small(ledger):
    def endless(endpoint, params, n):
        return envelope([comment(n * 100 + i) for i in range(15)], cursor=f"c{n}", has_more=True)

    client = FakeTS(endless)
    await TrueScrapeBackend("instagram", client=client, ledger=ledger).fetch_post_comments(ig_post(), 100000)
    assert len(client.calls) == MAX_INSTAGRAM_PAGES == 45

    small = FakeTS(endless)
    await TrueScrapeBackend("instagram", client=small, ledger=ledger).fetch_post_comments(ig_post("https://www.instagram.com/p/BBB/"), 20)
    assert len(small.calls) == 2                                      # 20 comments need 2 pages, not 8


@pytest.mark.asyncio
async def test_pages_already_paid_for_are_kept_when_the_budget_runs_out_mid_post(ledger, monkeypatch):
    from server.collection.collectors.base import CollectorFatalError
    monkeypatch.setenv("BUDGET_TRUESCRAPE_PER_JOB", "3")

    def pages(endpoint, params, n):
        return envelope([comment(n * 100 + i) for i in range(15)], cursor=f"c{n}", has_more=True)

    client = FakeTS(pages)
    be = TrueScrapeBackend("instagram", client=client, ledger=ledger)
    rows = await be.fetch_post_comments(ig_post(), 500)
    assert len(rows) == 45 and len(client.calls) == 3                 # three pages bought, then the cap: nothing thrown away
    with pytest.raises(CollectorFatalError, match="limit"):
        await be.fetch_post_comments(ig_post("https://www.instagram.com/p/NEXT/"), 500)   # a fresh post fails from page one


# ---- post facts + profile grid --------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_instagram_post_returns_owner_and_counts_and_is_cached(ledger):
    item = {"id": "AAA", "url": "https://www.instagram.com/p/AAA/", "authorHandle": "mmtf_official", "text": "cap", "commentCount": 42,
            "publishedAt": "2026-10-01"}
    client = FakeTS(lambda e, p, n: {"success": True, "data": item, "meta": {"creditsCharged": 1}})
    be = TrueScrapeBackend("instagram", client=client, ledger=ledger)
    facts = await be.instagram_post("https://www.instagram.com/p/AAA/")
    assert facts == {"post_id": "AAA", "url": "https://www.instagram.com/p/AAA/", "author_handle": "mmtf_official", "caption": "cap",
                     "comment_count": 42, "published_at": "2026-10-01"}
    await TrueScrapeBackend("instagram", client=client, ledger=ledger).instagram_post("https://www.instagram.com/p/AAA/")
    assert len(client.calls) == 1                                     # second lookup is free


@pytest.mark.asyncio
async def test_missing_counts_stay_unknown_rather_than_zero(ledger):
    client = FakeTS(lambda e, p, n: {"success": True, "data": {"url": "https://www.instagram.com/p/Z/", "authorHandle": "a", "commentCount": None}})
    facts = await TrueScrapeBackend("instagram", client=client, ledger=ledger).instagram_post("https://www.instagram.com/p/Z/")
    assert facts["comment_count"] is None


@pytest.mark.asyncio
async def test_profile_grid_is_paged_deduplicated_and_capped(ledger):
    def handler(endpoint, params, n):
        items = [{"id": f"P{n}{i}", "url": f"https://www.instagram.com/p/P{n}{i}/", "authorHandle": "mmtf_official"} for i in range(12)]
        items.append({"id": "P11", "url": "https://www.instagram.com/p/P11/", "authorHandle": "mmtf_official"})   # a repeat
        return envelope(items, cursor=f"c{n}", has_more=True)

    client = FakeTS(handler)
    posts = await TrueScrapeBackend("instagram", client=client, ledger=ledger).instagram_user_posts("@mmtf_official", 20)
    assert len(posts) == 20 and len({p["url"] for p in posts}) == 20
    assert client.calls[0][1] == {"handle": "mmtf_official"} and len(client.calls) == 2


@pytest.mark.asyncio
async def test_post_helpers_are_instagram_only(ledger):
    be = TrueScrapeBackend("reddit", client=FakeTS(lambda *a: {}), ledger=ledger)
    with pytest.raises(ValueError):
        await be.instagram_post("https://x")
    with pytest.raises(ValueError):
        await be.instagram_user_posts("x", 3)


# ---- ledger: cached payloads hold raw comments, so they must not outlive their TTL ------------------------------------
def test_expired_cache_rows_are_purged_when_the_ledger_is_opened_and_on_demand(tmp_path):
    import sqlite3
    path = str(tmp_path / "ledger.db")
    first = ProviderLedger(path)
    first.cache_put("old", "truescrape", {"comments": ["x"]}, ttl=-5)
    first.cache_put("fresh", "truescrape", {"a": 1}, ttl=600)
    first.cache_put("old2", "truescrape", {"a": 2}, ttl=-5)
    assert first.purge_expired() == 2
    first.cache_put("old3", "truescrape", {"a": 3}, ttl=-5)
    ProviderLedger(path).cache_get("fresh")                           # a new process opening the ledger cleans up
    rows = sqlite3.connect(path).execute("SELECT cache_key FROM api_cache").fetchall()
    assert rows == [("fresh",)]
