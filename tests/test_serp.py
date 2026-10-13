"""Bright Data SERP: client (headers/retries/auth), metering, and the discovery backend. All offline."""

import datetime
import json

import httpx
import pytest

from server.collection.collectors.base import CollectorFatalError
from server.collection.collectors.serp import SerpDiscoveryBackend, SerpSearch
from server.collection.ledger import ProviderLedger
from server.collection.models import QueryPlan
from server.providers.brightdata.serp import (
    MAX_ATTEMPTS,
    BrightDataSerpAuthError,
    BrightDataSerpClient,
    BrightDataSerpError,
    SerpPage,
    SerpResult,
    ignored_site_operator,
    parse_age,
    parse_likes,
)


def organic(link, source="", display="", title="t", description="d", rank=1):
    return {"link": link, "source": source, "display_link": display, "title": title,
            "description": description, "rank": rank}


def payload(items, next_start=10, total=957):
    return {"general": {"results_cnt": total}, "organic": items,
            "pagination": {"next_page_start": next_start, "pages": [{"page": 2, "start": 10}]}}


def make_client(handler, **kw):
    transport = httpx.MockTransport(handler)
    return BrightDataSerpClient(api_key="key", zone="serp_api1", client=httpx.AsyncClient(transport=transport),
                                retry_delay=0, **kw)


# ---- display-line parsing ---------------------------------------------------------------
def test_parse_likes():
    assert parse_likes("4.9K+ likes · 20 hours ago") == 4900
    assert parse_likes("400+ likes · 3 months ago") == 400
    assert parse_likes("3 likes · 4 months ago") == 3
    assert parse_likes("1.2M likes") == 1_200_000
    assert parse_likes("460+ followers") is None  # followers are not likes
    assert parse_likes("") is None


def test_parse_age_is_relative_to_now():
    now = datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.timezone.utc)
    assert parse_age("4.9K+ likes · 20 hours ago", now).startswith("2026-10-12T16:00")
    assert parse_age("3 months ago", now).startswith("2026-07-15")
    assert parse_age("130+ likes", now) is None


# ---- client -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_shape_and_parsing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=payload([organic("https://x.com/a/status/1", "X · a", "130+ likes", rank=1)]),
                              headers={"x-brd-status-code": "200"})

    page = await make_client(handler).search('site:x.com "anxiety"', start=10, tbs="qdr:m", country="IN")
    assert seen["auth"] == "Bearer key"
    assert seen["body"]["zone"] == "serp_api1" and seen["body"]["format"] == "raw"
    url = seen["body"]["url"]
    for part in ("brd_json=1", "tbs=qdr%3Am", "start=10", "gl=in", "q=site%3Ax.com+%22anxiety%22"):
        assert part in url
    assert [r.url for r in page.results] == ["https://x.com/a/status/1"]
    assert page.results[0].source == "X · a" and page.next_start == 10 and page.total == 957


@pytest.mark.asyncio
async def test_http_200_with_upstream_captcha_is_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:  # what Bright Data really sent: HTTP 200, empty body, failure only in headers
            return httpx.Response(200, headers={"x-brd-status-code": "502", "x-brd-error-code": "captcha"})
        return httpx.Response(200, json=payload([organic("https://x.com/a/status/1")]), headers={"x-brd-status-code": "200"})

    page = await make_client(handler).search("q")
    assert len(calls) == 2 and len(page.results) == 1


@pytest.mark.asyncio
async def test_rejected_query_429_is_transient_and_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:  # seen live on result page 2; the same request succeeded moments later
            return httpx.Response(200, headers={"x-brd-status-code": "429", "x-brd-error-code": "failed_query_rejected"})
        return httpx.Response(200, json=payload([organic("https://x.com/a/status/1")]), headers={"x-brd-status-code": "200"})

    page = await make_client(handler).search("q", start=10)
    assert len(calls) == 2 and len(page.results) == 1


@pytest.mark.asyncio
async def test_permanent_upstream_error_is_not_retried_and_message_is_honest():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, headers={"x-brd-status-code": "400", "x-brd-error-code": "invalid_query"})

    with pytest.raises(BrightDataSerpError, match=r"after 1 attempt\(s\).*invalid_query"):
        await make_client(handler).search("q")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_persistent_failure_raises_after_max_attempts():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, headers={"x-brd-status-code": "502", "x-brd-error-code": "captcha"})

    with pytest.raises(BrightDataSerpError, match=rf"after {MAX_ATTEMPTS} attempt\(s\).*captcha"):
        await make_client(handler).search("q")
    assert len(calls) == MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_auth_and_zone_errors_are_not_retried():
    calls = []

    def unauthorized(request):
        calls.append(1)
        return httpx.Response(401, text="nope")

    with pytest.raises(BrightDataSerpAuthError):
        await make_client(unauthorized).search("q")
    assert len(calls) == 1

    def bad_zone(request):
        return httpx.Response(400, text='{"error":"zone not found"}')

    with pytest.raises(BrightDataSerpAuthError, match="zone"):
        await make_client(bad_zone).search("q")


@pytest.mark.asyncio
async def test_no_results_is_a_success_and_missing_zone_is_reported():
    page = await make_client(lambda r: httpx.Response(200, json={"general": {}, "navigation": []},
                                                      headers={"x-brd-status-code": "200"})).search("q")
    assert page.results == [] and page.next_start is None

    unconfigured = BrightDataSerpClient(api_key="key", zone=None, settings=_Settings())
    assert not unconfigured.is_configured
    with pytest.raises(BrightDataSerpAuthError, match="BRIGHTDATA_SERP_ZONE"):
        await unconfigured.search("q")


class _Settings:
    brightdata_api_key = "key"
    brightdata_serp_zone = None
    brightdata_serp_country = None
    brightdata_base_url = "https://api.brightdata.com"
    brightdata_timeout = 30.0


# ---- metering ---------------------------------------------------------------------------
@pytest.fixture
def ledger(tmp_path):
    return ProviderLedger(str(tmp_path / "serp.db"))


@pytest.mark.asyncio
async def test_repeat_search_is_cached_and_costs_nothing(ledger):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=payload([organic("https://x.com/a/status/1")]), headers={"x-brd-status-code": "200"})

    first = SerpSearch("x", client=make_client(handler), ledger=ledger)
    await first.search("anxiety")
    second = SerpSearch("x", client=make_client(handler), ledger=ledger)  # a later job
    page = await second.search("anxiety")
    assert len(calls) == 1 and first.credits_used == 1 and second.credits_used == 0
    assert page.results[0].url.endswith("/status/1")
    assert ledger.summary()["providers"]["brightdata"]["cache_hits"] == 1


@pytest.mark.asyncio
async def test_job_budget_stops_further_searches(ledger, monkeypatch):
    monkeypatch.setenv("BUDGET_BRIGHTDATA_PER_JOB", "2")

    def handler(request):
        return httpx.Response(200, json=payload([]), headers={"x-brd-status-code": "200"})

    s = SerpSearch("x", client=make_client(handler), ledger=ledger)
    await s.search("a")
    await s.search("b")
    with pytest.raises(CollectorFatalError, match="limit"):
        await s.search("c")


@pytest.mark.asyncio
async def test_bad_key_blocks_the_provider(ledger):
    s = SerpSearch("x", client=make_client(lambda r: httpx.Response(401, text="no")), ledger=ledger)
    with pytest.raises(CollectorFatalError):
        await s.search("q")
    assert ledger.blocked_reason("brightdata") and not s.is_available()


# ---- discovery backend ------------------------------------------------------------------
class FakeSearch:
    def __init__(self, pages=None, error=None):
        self.pages, self.error, self.queries = list(pages or []), error, []
        self.credits_used = 0.0

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    async def search(self, query, start=0, tbs=None, country=None):
        self.queries.append((query, start, tbs))
        if self.error:
            raise self.error
        return self.pages.pop(0) if self.pages else SerpPage(query=query)


def page(*results, next_start=None):
    return SerpPage(query="q", results=list(results), next_start=next_start)


def res(url, source="", display="", title="t", snippet="s", rank=1):
    return SerpResult(rank=rank, url=url, title=title, snippet=snippet, source=source, display=display)


@pytest.mark.asyncio
async def test_x_candidates_are_canonical_deduped_and_carry_real_metrics():
    fake = FakeSearch([page(
        res("https://x.com/AnxietyUK/status/111/photo/1", "X · AnxietyUK", "1.2K+ likes · 2 days ago", snippet="tweet text"),
        res("https://twitter.com/AnxietyUK/status/111", snippet="same tweet"),
        res("https://x.com/AnxietyUK", snippet="a profile, not a post"),
        res("https://x.com/other/status/222", display="12 likes"),
    )])
    found = await SerpDiscoveryBackend("x", search=fake).discover(QueryPlan(topic="anxiety therapy", keywords=[]), 20)
    assert [c.url for c in found] == ["https://x.com/AnxietyUK/status/111", "https://x.com/other/status/222"]
    first = found[0]
    assert (first.post_id, first.author_username, first.like_count, first.text) == ("111", "AnxietyUK", 1200, "tweet text")
    assert first.published_at and first.extra["published_approx"] is True
    assert found[1].published_at is None and found[1].comment_count is None  # unknown stays unknown
    assert fake.queries[0][0] == 'site:x.com inurl:status "anxiety therapy"' and fake.queries[0][2] == "qdr:m"


@pytest.mark.asyncio
async def test_instagram_urls_are_canonical_and_author_comes_from_source():
    fake = FakeSearch([page(
        res("https://www.instagram.com/reel/DeZfKNzsQuS/", "Instagram · drjulie", "4.9K+ likes · 20 hours ago"),
        res("https://www.instagram.com/mann.talks/p/DbsxVdzkyK1/", "Instagram · mann.talks"),
        res("https://www.instagram.com/drjulie/", "Instagram · drjulie"),  # profile page: not a post
    )])
    found = await SerpDiscoveryBackend("instagram", search=fake).discover(QueryPlan(topic="anxiety"), 20)
    assert [c.url for c in found] == ["https://www.instagram.com/reel/DeZfKNzsQuS/", "https://www.instagram.com/p/DbsxVdzkyK1/"]
    assert found[0].author_username == "drjulie" and found[0].like_count == 4900
    assert fake.queries[0][0] == "site:instagram.com anxiety" and fake.queries[0][2] is None  # no date filter


@pytest.mark.asyncio
async def test_linkedin_only_keeps_posts_not_profiles():
    fake = FakeSearch([page(
        res("https://www.linkedin.com/posts/someone_cbt-for-anxiety-activity-123-abcd", "LinkedIn · Some One"),
        res("https://in.linkedin.com/in/clarissa-s-764b7a264", "LinkedIn · Clarissa S"),
    )])
    found = await SerpDiscoveryBackend("linkedin", search=fake).discover(QueryPlan(topic="anxiety"), 20)
    assert len(found) == 1 and "/posts/" in found[0].url and found[0].author_username == "Some One"


@pytest.mark.asyncio
async def test_follows_pagination_but_stops_at_the_page_cap_and_the_limit():
    pages = [page(res(f"https://x.com/u/status/{i}"), next_start=10) for i in range(1, 9)]
    fake = FakeSearch(pages)
    found = await SerpDiscoveryBackend("x", search=fake).discover(QueryPlan(topic="a", keywords=["b", "c"]), 100)
    assert len(fake.queries) == 3 * 2  # 3 queries x MAX_PAGES, never more credits than that
    assert fake.queries[1][1] == 10 and len(found) == 6

    fake = FakeSearch([page(*[res(f"https://x.com/u/status/{i}") for i in range(5)], next_start=10)])
    limited = await SerpDiscoveryBackend("x", search=fake).discover(QueryPlan(topic="a"), 3)
    assert len(fake.queries) == 1 and len(limited) == 5  # limit reached after the first page: no second credit


@pytest.mark.asyncio
async def test_quotes_in_topic_cannot_break_the_query():
    fake = FakeSearch([page()])
    await SerpDiscoveryBackend("x", search=fake).discover(QueryPlan(topic='the "big" topic', keywords=[]), 5)
    assert fake.queries[0][0] == 'site:x.com inurl:status "the big topic"'


@pytest.mark.asyncio
async def test_all_searches_failing_is_an_error_but_fatal_errors_pass_through():
    with pytest.raises(BrightDataSerpError):
        await SerpDiscoveryBackend("x", search=FakeSearch(error=BrightDataSerpError("captcha"))).discover(QueryPlan(topic="a"), 5)
    with pytest.raises(CollectorFatalError):
        await SerpDiscoveryBackend("x", search=FakeSearch(error=CollectorFatalError("daily limit"))).discover(QueryPlan(topic="a"), 5)


@pytest.mark.asyncio
async def test_backend_cannot_read_comments_and_rejects_other_platforms():
    backend = SerpDiscoveryBackend("x", search=FakeSearch())
    assert backend.can_discover and not backend.can_comments
    assert await backend.fetch_post_comments(None, 10) == []
    with pytest.raises(ValueError):
        SerpDiscoveryBackend("youtube")


# ---- wiring -----------------------------------------------------------------------------
def test_chains_use_serp_only_when_a_zone_is_configured(monkeypatch):
    from server.collection.registry import get_collector
    from server.config import get_settings

    monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
    get_settings(reload=True)
    x = get_collector("x").describe()
    assert "brightdata" not in x["discover"]
    assert "BRIGHTDATA_SERP_ZONE" in x["unavailable"]["brightdata"]

    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
    get_settings(reload=True)
    # tests blank the twitter-cli cookies and the SocialCrawl key, so SERP is the only X discovery left
    assert get_collector("x").describe()["discover"] == ["brightdata"]
    ig = get_collector("instagram").describe()
    assert ig["discover"][0] == "brightdata"  # cheapest way to find Instagram posts goes first
    assert "brightdata" not in ig["comments"]


# ---- Google sometimes ignores site: (and Bright Data still bills the page) ---------------
def test_ignored_site_operator_detection():
    li = [SerpResult(i, f"https://in.linkedin.com/in/p{i}") for i in range(10)]
    junk = [SerpResult(i, f"https://www.apa.org/a{i}") for i in range(10)]
    assert not ignored_site_operator("site:linkedin.com/in psychologist", li)
    assert ignored_site_operator("site:linkedin.com/in psychologist", junk)
    assert ignored_site_operator("site:linkedin.com/in psychologist", li[:3] + junk[:7])
    assert not ignored_site_operator("psychologist bangalore", junk)  # no site: filter asked for
    assert not ignored_site_operator("site:x.com anxiety", [])
    assert not ignored_site_operator("site:instagram.com anxiety", [SerpResult(1, "https://www.instagram.com/p/a/")])


@pytest.mark.asyncio
async def test_degraded_page_is_flagged_billed_but_never_cached(ledger):
    calls = []

    def handler(request):
        calls.append(1)
        junk = [organic(f"https://www.apa.org/a{i}") for i in range(4)]
        return httpx.Response(200, json=payload(junk), headers={"x-brd-status-code": "200"})

    s = SerpSearch("web", client=make_client(handler), ledger=ledger)
    first = await s.search("site:linkedin.com/in psychologist")
    again = await s.search("site:linkedin.com/in psychologist")  # must go back to the API, not replay junk
    assert first.degraded and again.degraded
    assert len(calls) == 2 and s.credits_used == 2


@pytest.mark.asyncio
async def test_good_page_is_cached_and_not_flagged(ledger):
    calls = []

    def handler(request):
        calls.append(1)
        items = [organic(f"https://in.linkedin.com/in/p{i}") for i in range(4)]
        return httpx.Response(200, json=payload(items), headers={"x-brd-status-code": "200"})

    s = SerpSearch("web", client=make_client(handler), ledger=ledger)
    assert not (await s.search("site:linkedin.com/in psychologist")).degraded
    await s.search("site:linkedin.com/in psychologist")
    assert len(calls) == 1
