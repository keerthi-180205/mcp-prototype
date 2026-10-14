"""Provider layer: ledger (cache/budget/blocked), TrueScrape + SocialCrawl backends, fallback chain.

All offline. Payloads are synthetic but follow the shapes verified against the live APIs.
"""

import pytest

from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.collectors.chain import ChainedCollector
from server.collection.collectors.socialcrawl import SocialCrawlBackend, parse_comment, parse_post
from server.collection.collectors.truescrape import TrueScrapeBackend
from server.collection.ledger import BudgetExceeded, ProviderLedger
from server.collection.models import CommentRow, PostCandidate, QueryPlan
from server.providers.socialcrawl.client import SocialCrawlError
from server.providers.truescrape.client import TrueScrapeError


@pytest.fixture
def ledger(tmp_path):
    return ProviderLedger(str(tmp_path / "ledger.db"))


def post(url="https://x.test/p1", **kw):
    return PostCandidate(platform=kw.pop("platform", "reddit"), post_id=url, url=url, comment_count=5, **kw)


# ---- ledger ---------------------------------------------------------------------------
def test_cache_roundtrip_and_expiry(ledger):
    ledger.cache_put("k", "truescrape", {"a": 1}, ttl=60)
    assert ledger.cache_get("k") == {"a": 1}
    ledger.cache_put("old", "truescrape", {"a": 1}, ttl=-1)
    assert ledger.cache_get("old") is None


def test_budget_per_job_and_per_day(ledger, monkeypatch):
    monkeypatch.setenv("BUDGET_TRUESCRAPE_PER_JOB", "3")
    monkeypatch.setenv("BUDGET_TRUESCRAPE_PER_DAY", "5")
    ledger.check_budget("truescrape", 1, spent_this_job=2)  # 3rd credit fits
    with pytest.raises(BudgetExceeded):
        ledger.check_budget("truescrape", 1, spent_this_job=3)
    for _ in range(5):
        ledger.record_usage("truescrape", "reddit", "comments", credits=1)
    with pytest.raises(BudgetExceeded):
        ledger.check_budget("truescrape", 1, spent_this_job=0)


def test_cache_hits_do_not_count_against_budget(ledger, monkeypatch):
    monkeypatch.setenv("BUDGET_TRUESCRAPE_PER_DAY", "2")
    for _ in range(10):
        ledger.record_usage("truescrape", "reddit", "comments", credits=1, cached=True)
    ledger.check_budget("truescrape", 1, spent_this_job=0)
    assert ledger.summary()["providers"]["truescrape"]["cache_hits"] == 10


def test_blocked_state(ledger):
    assert ledger.blocked_reason("socialcrawl") is None
    ledger.set_blocked("socialcrawl", "no credits")
    assert ledger.blocked_reason("socialcrawl") == "no credits"


# ---- TrueScrape backend ---------------------------------------------------------------
class FakeTS:
    is_configured = True

    def __init__(self, pages=None, error=None):
        self.pages = list(pages or [])
        self.error = error
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, dict(params or {})))
        if self.error:
            raise self.error
        return self.pages.pop(0)


def ts_envelope(items, cursor=None, has_more=False, charged=1):
    return {
        "success": True,
        "data": {"items": items},
        "pagination": {"cursor": cursor, "hasMore": has_more, "count": len(items)},
        "meta": {"creditsCharged": charged, "cached": False},
    }


def ts_comment(i, **kw):
    base = {"id": f"c{i}", "parentId": None, "text": f"comment {i}", "authorId": f"t2_{i}",
            "authorHandle": f"user{i}", "likeCount": i, "publishedAt": "2026-10-01T00:00:00Z"}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_truescrape_reddit_comments_keep_thread_and_provenance(ledger):
    items = [
        ts_comment(1),
        ts_comment(2, parentId="c1"),
        ts_comment(3, authorHandle="AutoModerator"),
        ts_comment(4, text="[removed]"),
        ts_comment(5, isAuthorReply=True),
    ]
    be = TrueScrapeBackend("reddit", client=FakeTS([ts_envelope(items)]), ledger=ledger)
    rows = await be.fetch_post_comments(post("https://reddit.test/r/a/comments/1/x"), 50)
    assert [r.comment_id for r in rows] == ["c1", "c2"]
    assert rows[1].parent_id == "c1"
    assert rows[0].user_id == "t2_1" and rows[0].username == "user1"
    assert all(r.provider == "truescrape" for r in rows)
    assert be.credits_used == 1


@pytest.mark.asyncio
async def test_truescrape_second_identical_call_is_served_from_cache(ledger):
    client = FakeTS([ts_envelope([ts_comment(1)])])
    p = post("https://reddit.test/r/a/comments/1/x")
    await TrueScrapeBackend("reddit", client=client, ledger=ledger).fetch_post_comments(p, 50)
    again = TrueScrapeBackend("reddit", client=client, ledger=ledger)  # new job, new instance
    rows = await again.fetch_post_comments(p, 50)
    assert len(client.calls) == 1 and len(rows) == 1
    assert again.credits_used == 0


@pytest.mark.asyncio
async def test_truescrape_budget_limit_is_fatal_for_the_provider(ledger, monkeypatch):
    monkeypatch.setenv("BUDGET_TRUESCRAPE_PER_JOB", "1")
    client = FakeTS([ts_envelope([ts_comment(1)]), ts_envelope([ts_comment(2)])])
    be = TrueScrapeBackend("reddit", client=client, ledger=ledger)
    await be.fetch_post_comments(post("https://reddit.test/1"), 10)
    with pytest.raises(CollectorFatalError, match="limit"):
        await be.fetch_post_comments(post("https://reddit.test/2"), 10)
    assert len(client.calls) == 1  # the second paid call was never made


@pytest.mark.asyncio
async def test_truescrape_out_of_credits_blocks_provider(ledger):
    be = TrueScrapeBackend("reddit", client=FakeTS(error=TrueScrapeError("TrueScrape API error (HTTP 402): no credit")), ledger=ledger)
    with pytest.raises(CollectorFatalError):
        await be.fetch_post_comments(post(), 10)
    assert ledger.blocked_reason("truescrape")
    assert not be.is_available()


@pytest.mark.asyncio
async def test_truescrape_instagram_pages_until_enough(ledger):
    pages = [
        ts_envelope([ts_comment(i) for i in range(1, 6)], cursor="c2", has_more=True),
        ts_envelope([ts_comment(i) for i in range(6, 11)], cursor="c3", has_more=True),
        ts_envelope([ts_comment(i) for i in range(11, 16)], cursor=None, has_more=False),
    ]
    client = FakeTS(pages)
    be = TrueScrapeBackend("instagram", client=client, ledger=ledger)
    rows = await be.fetch_post_comments(post("https://www.instagram.com/reel/AAA/", platform="instagram"), 8)
    assert len(rows) == 8
    assert len(client.calls) == 2  # stopped as soon as it had enough
    assert client.calls[1][1]["cursor"] == "c2"


def test_truescrape_instagram_cannot_discover(ledger):
    be = TrueScrapeBackend("instagram", client=FakeTS(), ledger=ledger)
    assert be.can_comments and not be.can_discover
    with pytest.raises(ValueError):
        TrueScrapeBackend("linkedin")


@pytest.mark.asyncio
async def test_truescrape_reddit_discover_skips_posts_without_comments(ledger):
    item = lambda i, n: {"id": f"p{i}", "url": f"https://reddit.test/{i}", "title": "t", "commentCount": n,
                         "authorHandle": "a", "authorId": "t2_a", "publishedAt": "2026-10-01T00:00:00Z"}
    client = FakeTS([ts_envelope([item(1, 9), item(2, 0)])] * 5)
    be = TrueScrapeBackend("reddit", client=client, ledger=ledger)
    found = await be.discover(QueryPlan(topic="anxiety", keywords=["anxiety"], subreddits=[]), 20)
    assert [c.post_id for c in found] == ["p1"]


# ---- SocialCrawl parsing --------------------------------------------------------------
def test_socialcrawl_parse_never_invents_data():
    assert parse_post("linkedin", {"post": {"id": "1"}}) is None  # no url
    assert parse_post("x", {"post": {"url": "https://x.test/1", "engagement": {"replies": 0}}}) is None
    c = parse_post("linkedin", {"post": {"id": "9", "url": "https://li.test/9", "content": {"text": "hello"}}})
    assert c.comment_count is None and c.author_username is None  # unknown stays unknown

    row = parse_comment("linkedin", {"comment": {"content": {"text": "nice"}}}, "https://li.test/9", "socialcrawl")
    assert row.username == "" and row.user_id is None
    assert parse_comment("linkedin", {"comment": {"content": {"text": "  "}}}, "u", "socialcrawl") is None


class FakeSC:
    is_configured = True
    last_credits_remaining = None

    def __init__(self, error=None, payload=None):
        self.error, self.payload, self.calls = error, payload, 0

    async def get_linkedin_comments(self, post_url, cursor=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


@pytest.mark.asyncio
async def test_socialcrawl_no_credits_is_fatal_and_remembered(ledger):
    err = SocialCrawlError('SocialCrawl API error (402): {"type":"INSUFFICIENT_CREDITS"}')
    be = SocialCrawlBackend("linkedin", client=FakeSC(error=err), ledger=ledger)
    with pytest.raises(CollectorFatalError, match="no credits"):
        await be.fetch_post_comments(post("https://li.test/1", platform="linkedin"), 10)
    assert "no credits" in ledger.blocked_reason("socialcrawl")


@pytest.mark.asyncio
async def test_socialcrawl_comments_parsed(ledger):
    payload = {"credits_used": 1, "data": {"items": [
        {"comment": {"id": "a", "content": {"text": "great post"}, "author": {"id": "7", "name": "Asha"}, "metrics": {"likes": 3}}},
    ]}}
    be = SocialCrawlBackend("linkedin", client=FakeSC(payload=payload), ledger=ledger)
    rows = await be.fetch_post_comments(post("https://li.test/1", platform="linkedin"), 10)
    assert (rows[0].username, rows[0].user_id, rows[0].likes, rows[0].provider) == ("Asha", "7", 3, "socialcrawl")


# ---- chain ----------------------------------------------------------------------------
class Fake(PlatformCollector):
    platform = "reddit"

    def __init__(self, provider, *, discover=None, comments=None, error=None, can_discover=True, can_comments=True, available=True):
        self.provider = provider
        self._discover, self._comments, self._error = discover or [], comments, error
        self.can_discover, self.can_comments, self._available = can_discover, can_comments, available
        self.fetch_calls = []

    def is_available(self):
        return self._available

    def unavailable_reason(self):
        return "not configured"

    async def discover(self, plan, limit):
        if self._error:
            raise self._error
        return list(self._discover)

    async def fetch_post_comments(self, p, n):
        return (await self.fetch_comments([p], {p.url: n}))[p.url]

    async def fetch_comments(self, posts, per_post_limit):
        self.fetch_calls.append([p.url for p in posts])
        if self._error:
            raise self._error
        return {u: rows for u, rows in (self._comments or {}).items() if u in {p.url for p in posts}}


def row(url, text="hi"):
    return CommentRow(platform="reddit", username="u", comment=text, post_url=url)


@pytest.mark.asyncio
async def test_chain_falls_through_on_fatal_and_tags_provider():
    a = Fake("free", error=CollectorFatalError("cookie expired"))
    b = Fake("paid", comments={"u1": [row("u1")]})
    chain = ChainedCollector("reddit", [a, b])
    got = await chain.fetch_comments([post("u1")], {})
    assert got["u1"][0].provider == "paid"
    assert chain.served == {"paid": 1}
    assert any("free switched off" in n for n in chain.notes)
    assert chain.describe()["comments"] == ["paid"]


@pytest.mark.asyncio
async def test_chain_never_rebuys_a_post_that_was_answered_empty():
    a = Fake("free", comments={"u1": []})  # answered: no comments
    b = Fake("paid", comments={"u1": [row("u1")]})
    chain = ChainedCollector("reddit", [a, b])
    got = await chain.fetch_comments([post("u1")], {})
    assert got == {"u1": []} and b.fetch_calls == []


@pytest.mark.asyncio
async def test_chain_sends_only_unanswered_posts_to_next_provider():
    a = Fake("free", comments={"u1": [row("u1")]})  # u2 missing = it failed
    b = Fake("paid", comments={"u2": [row("u2")]})
    chain = ChainedCollector("reddit", [a, b])
    got = await chain.fetch_comments([post("u1"), post("u2")], {})
    assert set(got) == {"u1", "u2"} and b.fetch_calls == [["u2"]]


@pytest.mark.asyncio
async def test_chain_discover_uses_first_provider_that_finds_posts_and_skips_incapable():
    cant = Fake("blind", can_discover=False, discover=[post("nope")])
    empty = Fake("empty")
    good = Fake("good", discover=[post("u1")])
    spare = Fake("spare", discover=[post("u9")])
    chain = ChainedCollector("reddit", [cant, empty, good, spare])
    found = await chain.discover(QueryPlan(topic="t"), 10)
    assert [c.url for c in found] == ["u1"] and found[0].extra["discovered_by"] == "good"


@pytest.mark.asyncio
async def test_chain_error_semantics():
    boom = ChainedCollector("reddit", [Fake("a", error=RuntimeError("500")), Fake("b", error=RuntimeError("502"))])
    with pytest.raises(RuntimeError):  # non-fatal: harvester counts consecutive failures
        await boom.fetch_comments([post("u1")], {})

    dead = ChainedCollector("reddit", [Fake("a", error=CollectorFatalError("bad key"))])
    with pytest.raises(CollectorFatalError):
        await dead.fetch_comments([post("u1")], {})
    assert not dead.is_available()


def test_chain_budget_exhausted_only_when_every_provider_is_out_of_budget():
    a, b = Fake("a"), Fake("b")
    chain = ChainedCollector("reddit", [a, b])
    assert not chain.budget_exhausted()
    chain._disable(a, "daily limit reached", budget=True)
    assert not chain.budget_exhausted()  # b still works
    chain._disable(b, "no credits", budget=True)
    assert chain.budget_exhausted()

    errored = ChainedCollector("reddit", [Fake("a")])
    errored._disable(errored.backends[0], "bad key", budget=False)
    assert not errored.budget_exhausted()  # an auth error is an error, not a budget stop


def test_chain_availability_needs_discover_and_comments():
    only_comments = ChainedCollector("instagram", [Fake("ts", can_discover=False)])
    assert not only_comments.is_available()
    assert "discover" in only_comments.unavailable_reason()
    both = ChainedCollector("instagram", [Fake("ts", can_discover=False), Fake("apify")])
    assert both.is_available()


def test_availability_reflects_real_chain(monkeypatch):
    from server.chat.assistant import get_platforms_availability

    monkeypatch.setenv("TRUESCRAPE_API_KEY", "k")
    from server.config import get_settings

    get_settings(reload=True)
    ig = get_platforms_availability()["instagram"]
    # TrueScrape can read Instagram comments but cannot find posts, and nothing else is configured
    assert ig["available"] is False
    assert ig["providers"]["comments"] == ["truescrape"] and ig["providers"]["discover"] == []
    assert "find posts" in ig["reason"]
    assert get_platforms_availability()["linkedin"]["available"] is False  # no more hardcoded True


# ---- failures are reported, not hidden ---------------------------------------------------
@pytest.mark.asyncio
async def test_chain_discover_explains_why_nothing_was_found():
    empty = Fake("free", error=RuntimeError("HTTP 404"))
    broke = Fake("paid", error=CollectorFatalError("no credits left"))
    chain = ChainedCollector("x", [empty, broke])
    with pytest.raises(CollectorFatalError) as err:
        await chain.discover(QueryPlan(topic="t"), 10)
    msg = str(err.value)
    assert "free: HTTP 404" in msg and "paid: no credits left" in msg


@pytest.mark.asyncio
async def test_chain_discover_genuinely_empty_is_not_an_error():
    chain = ChainedCollector("x", [Fake("free"), Fake("paid")])
    assert await chain.discover(QueryPlan(topic="t"), 10) == []


@pytest.mark.asyncio
async def test_x_collector_raises_when_every_search_errors(monkeypatch):
    import server.collection.collectors.x as xc
    from server.collection.cli import CliError

    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "a" * 40)
    monkeypatch.setenv("TWITTER_CT0", "b" * 32)

    async def boom(*a, **k):
        raise CliError("twitter exited with code 1")

    monkeypatch.setattr(xc, "run_cli", boom)
    with pytest.raises(CliError, match="X searches failed"):
        await xc.XCollector(binary="twitter").discover(QueryPlan(topic="t", keywords=["t"]), 10)


# ---- a "no credits" block is remembered for hours, forgotten when the key changes, and can be cleared -----------------
def ttl_left(ledger, provider):
    import sqlite3
    conn = sqlite3.connect(ledger.db_path)
    row = conn.execute("SELECT expires_at - created_at FROM api_cache WHERE cache_key=?", (f"blocked|{provider}",)).fetchone()
    return row[0] if row else None


@pytest.mark.asyncio
async def test_no_credits_is_remembered_for_hours_but_a_rate_limit_only_briefly(ledger, monkeypatch):
    be = SocialCrawlBackend("linkedin", client=FakeSC(error=SocialCrawlError("SocialCrawl API error (402): INSUFFICIENT_CREDITS")), ledger=ledger)
    with pytest.raises(CollectorFatalError):
        await be.fetch_post_comments(post("https://li.test/1", platform="linkedin"), 5)
    assert 5.9 * 3600 < ttl_left(ledger, "socialcrawl") <= 6 * 3600 and not be.is_available()

    from server.providers.socialcrawl.client import SocialCrawlRateLimitError
    limited = SocialCrawlBackend("x", client=FakeSC(error=SocialCrawlRateLimitError("slow down")), ledger=ProviderLedger(ledger.db_path))
    ledger.clear_blocked("socialcrawl")
    monkeypatch.setattr(FakeSC, "get_tweet_replies", lambda self, tweet_url, cursor=None: self.get_linkedin_comments(tweet_url, cursor), raising=False)
    with pytest.raises(CollectorFatalError):
        await limited.fetch_post_comments(post("https://x.test/1", platform="x"), 5)
    assert ttl_left(ledger, "socialcrawl") <= 1800


@pytest.mark.asyncio
async def test_replacing_the_api_key_lifts_the_block_and_clear_blocked_does_too(ledger):
    class KeyedSC(FakeSC):
        def __init__(self, key, **kw):
            super().__init__(**kw)
            self._api_key = key

    err = SocialCrawlError("SocialCrawl API error (402): INSUFFICIENT_CREDITS")
    old = SocialCrawlBackend("linkedin", client=KeyedSC("old-key", error=err), ledger=ledger)
    with pytest.raises(CollectorFatalError):
        await old.fetch_post_comments(post("https://li.test/1", platform="linkedin"), 5)
    assert not old.is_available()
    assert SocialCrawlBackend("linkedin", client=KeyedSC("new-key"), ledger=ledger).is_available()     # different key: tried again
    assert not SocialCrawlBackend("linkedin", client=KeyedSC("old-key"), ledger=ledger).is_available()  # same key: still blocked
    assert ledger.clear_blocked("socialcrawl") is True and ledger.clear_blocked("socialcrawl") is False
    assert SocialCrawlBackend("linkedin", client=KeyedSC("old-key"), ledger=ledger).is_available()      # topped up and cleared


def test_the_availability_panel_shows_a_blocked_provider_with_its_reason(monkeypatch):
    from server.chat.assistant import get_platforms_availability
    from server.collection.ledger import get_ledger
    from server.config import get_settings

    monkeypatch.setenv("SOCIALCRAWL_API_KEY", "k")
    get_settings(reload=True)
    assert get_platforms_availability()["linkedin"]["available"] is True          # configured, nothing known yet
    get_ledger().set_blocked("socialcrawl", "SocialCrawl has no credits left (HTTP 402)", 3600)
    linkedin = get_platforms_availability()["linkedin"]
    assert linkedin["available"] is False and "no credits" in linkedin["unavailable_providers"]["socialcrawl"]


def test_unblock_endpoint_and_cli(monkeypatch, capsys):
    from starlette.testclient import TestClient
    from scripts import providers
    from server.collection.ledger import get_ledger
    from web.server import app

    get_ledger().set_blocked("socialcrawl", "no credits", 3600)
    with TestClient(app) as client:
        assert client.post("/api/providers/nope/unblock").status_code == 404
        assert client.post("/api/providers/socialcrawl/unblock").json() == {"status": "ok", "provider": "socialcrawl", "was_blocked": True}
        assert client.post("/api/providers/socialcrawl/unblock").json()["was_blocked"] is False
    get_ledger().set_blocked("truescrape", "out of credits", 3600)
    assert providers.unblock("truescrape") == 0 and "block cleared" in capsys.readouterr().out
    assert providers.status() == 0 and "Credits in the last 24h" in capsys.readouterr().out


# ---- the balance is read for free, so the panel is truthful before any job fails -----------------------------------
def sc_client(handler):
    import httpx
    from server.providers.socialcrawl.client import SocialCrawlClient
    return SocialCrawlClient(api_key="key", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_credit_balance_is_read_from_the_validation_error_body():
    import httpx
    body = '{"success":false,"error":{"type":"INVALID_REQUEST","status":400},"credits_used":0,"credits_remaining":37}'
    assert await sc_client(lambda r: httpx.Response(400, text=body)).credit_balance() == 37
    assert await sc_client(lambda r: httpx.Response(402, text='{"error":{"type":"INSUFFICIENT_CREDITS"}}')).credit_balance() == 0
    assert await sc_client(lambda r: httpx.Response(500, text="boom")).credit_balance() is None


@pytest.mark.asyncio
async def test_refresh_blocks_an_empty_account_and_unblocks_after_a_top_up(ledger):
    import httpx
    from server.collection.health import refresh_provider_state
    state = {"credits": 0}

    def handler(request):
        return httpx.Response(400, text='{"credits_remaining": %d}' % state["credits"])

    client = sc_client(handler)
    assert (await refresh_provider_state(ledger, client))["socialcrawl"]["blocked"] is True
    assert "no credits" in ledger.blocked_reason("socialcrawl")
    state["credits"] = 120                                                       # the account is topped up
    assert (await refresh_provider_state(ledger, client))["socialcrawl"] == {"configured": True, "balance": 120, "blocked": False}
    assert ledger.blocked_reason("socialcrawl") is None


@pytest.mark.asyncio
async def test_refresh_does_nothing_without_a_key_and_survives_outages(ledger):
    import httpx
    from server.collection.health import refresh_provider_state
    from server.providers.socialcrawl.client import SocialCrawlClient
    assert (await refresh_provider_state(ledger, SocialCrawlClient(api_key="")))["socialcrawl"] == {"configured": False}
    out = await refresh_provider_state(ledger, sc_client(lambda r: httpx.Response(500, text="down")))
    assert out["socialcrawl"]["balance"] is None and ledger.blocked_reason("socialcrawl") is None   # an outage is not "no credits"
