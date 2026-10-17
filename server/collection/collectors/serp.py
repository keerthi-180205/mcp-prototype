"""Bright Data SERP backend: find posts through Google when a platform's own search is closed or costly.

`site:x.com inurl:status "topic"` returns real tweet URLs, `site:instagram.com topic` real posts and
reels, `site:linkedin.com/posts topic` real LinkedIn posts. The backend only *discovers*: it cannot
read comments, so the chain pairs it with whoever can (twitter-cli for X replies, TrueScrape for
Instagram comments, SocialCrawl for LinkedIn).

Each Google result carries the author ("Instagram · dr.jud"), likes and a coarse age
("4.9K+ likes · 20 hours ago"). Those are used as-is; nothing is guessed. The age is approximate
because Google only gives "3 months ago", and the candidate is flagged `published_approx`.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.collectors.metered import MeteredMixin
from server.collection.ledger import ProviderLedger
from server.collection.models import CommentRow, PostCandidate, QueryPlan
from server.providers.brightdata.serp import (
    BrightDataSerpAuthError,
    BrightDataSerpClient,
    BrightDataSerpError,
    SerpPage,
    SerpResult,
    parse_age,
    parse_likes,
)

logger = logging.getLogger("mcp_server.collection.serp")

SEARCH_TTL = 6 * 3600
MAX_QUERIES = 3   # queries per job and platform
MAX_PAGES = 2     # Google result pages per query (1 credit each)

SUPPORTED = ("x", "instagram", "linkedin")

_X_STATUS = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)")
_IG_POST = re.compile(r"https?://(?:www\.)?instagram\.com/(?:([A-Za-z0-9_.]+)/)?(p|reels?|tv)/([A-Za-z0-9_-]+)")
_LI_POST = re.compile(r"https?://(?:[a-z]{2,3}\.|www\.)?linkedin\.com/(?:posts/[^\s?#]+|feed/update/urn:li:activity:\d+)")


class SerpSearch(MeteredMixin):
    """One Google search through Bright Data: cached, budgeted, and recorded in the ledger."""

    provider = "brightdata"

    def __init__(
        self,
        platform: str = "web",
        client: Optional[BrightDataSerpClient] = None,
        ledger: Optional[ProviderLedger] = None,
    ):
        self.platform = platform
        self._client = client
        self._ledger = ledger
        self.credits_used = 0.0

    @property
    def client(self) -> BrightDataSerpClient:
        if self._client is None:
            self._client = BrightDataSerpClient()
        return self._client

    def is_available(self) -> bool:
        return self.client.is_configured and not self.blocked_reason()

    def unavailable_reason(self) -> str:
        if not self.client.is_configured:
            return self.client.not_configured_reason()
        return self.blocked_reason() or "Bright Data SERP is not usable right now"

    @staticmethod
    def _map_error(exc: Exception) -> Optional[Exception]:
        if isinstance(exc, BrightDataSerpAuthError):
            return CollectorFatalError(f"Bright Data SERP: {str(exc)[:160]}")
        return None

    async def search(self, query: str, start: int = 0, tbs: Optional[str] = None, country: Optional[str] = None) -> SerpPage:
        async def _call() -> Dict[str, Any]:
            return (await self.client.search(query, start=start, tbs=tbs, country=country)).to_dict()

        payload = await self._metered(
            [query, start, tbs or "", country or self.client.country or ""],
            _call,
            "search",
            SEARCH_TTL,
            lambda _payload: 1.0,  # 1 credit per successful request, whatever the result count
            self._map_error,
            cache_if=lambda payload: not payload.get("degraded"),  # a page that ignored site: must not be replayed
        )
        return SerpPage.from_dict(payload)


def _handle(source: str) -> Optional[str]:
    """"Instagram · dr.jud" -> "dr.jud"."""
    if not source:
        return None
    for sep in ("·", "-", ":", "|"):
        if sep in source:
            parts = source.split(sep, 1)
            cand1 = parts[1].strip().lstrip("@")
            if cand1 and not cand1.lower().startswith("instagram") and not cand1.lower().startswith("linkedin"):
                return cand1
            cand0 = parts[0].strip().lstrip("@")
            if cand0 and not cand0.lower().startswith("instagram") and not cand0.lower().startswith("linkedin"):
                return cand0
    return None


class SerpDiscoveryBackend(PlatformCollector):
    provider = "brightdata"
    can_comments = False

    def __init__(self, platform: str, search: Optional[SerpSearch] = None):
        if platform not in SUPPORTED:
            raise ValueError(f"SERP discovery does not support {platform}")
        self.platform = platform
        self.search = search or SerpSearch(platform)

    def is_available(self) -> bool:
        return self.search.is_available()

    def unavailable_reason(self) -> str:
        return self.search.unavailable_reason()

    def usage(self) -> Dict[str, Any]:
        return {"credits_used": self.search.credits_used}

    # ---- queries -------------------------------------------------------------------
    def _queries(self, plan: QueryPlan) -> List[Dict[str, Optional[str]]]:
        terms = list(dict.fromkeys(t.replace('"', "").strip() for t in [plan.topic, *plan.keywords] if t and t.strip()))[:MAX_QUERIES]
        if self.platform == "x":
            # a month back: X is about what people say now; Instagram/LinkedIn are too thinly indexed for a date filter
            return [{"q": f'site:x.com inurl:status "{t}"', "tbs": "qdr:m"} for t in terms]
        if self.platform == "instagram":
            return [{"q": f"site:instagram.com {t}", "tbs": None} for t in terms]
        return [{"q": f"site:linkedin.com/posts {t}", "tbs": None} for t in terms]

    # ---- result -> candidate -------------------------------------------------------
    def _candidate(self, r: SerpResult) -> Optional[PostCandidate]:
        likes, published = parse_likes(r.display), parse_age(r.display)
        extra: Dict[str, Any] = {"serp_rank": r.rank, "serp_query_source": r.source}
        if published:
            extra["published_approx"] = True

        if self.platform == "x":
            m = _X_STATUS.match(r.url)
            if not m:
                return None
            user, tweet_id = m.group(1), m.group(2)
            text = r.snippet or r.title
            return PostCandidate(
                platform="x", post_id=tweet_id, url=f"https://x.com/{user}/status/{tweet_id}",
                title=text[:200], text=text, author_username=user,
                like_count=likes, published_at=published, extra=extra,
            )
        if self.platform == "instagram":
            m = _IG_POST.match(r.url)
            if not m:
                return None
            url_user = m.group(1)
            if url_user and url_user.lower() in ("p", "reel", "reels", "tv", "explore", "stories", "direct"):
                url_user = None
            kind = "reel" if m.group(2).startswith("reel") else m.group(2)
            code = m.group(3)

            author = (
                (url_user.lstrip("@").strip() if url_user else None)
                or _handle(r.source)
            )
            if not author and r.title:
                m_title = re.search(r"\(?@([A-Za-z0-9_.]+)\)?", r.title)
                if m_title:
                    author = m_title.group(1).strip()
            if not author and r.snippet:
                m_snip = re.search(r"(?:^|[\s·-])@?([A-Za-z0-9_.]+):\s|comments\s*-\s*([A-Za-z0-9_.]+)\s+on\b", r.snippet)
                if m_snip:
                    author = (m_snip.group(1) or m_snip.group(2)).strip()

            return PostCandidate(
                platform="instagram", post_id=code, url=f"https://www.instagram.com/{kind}/{code}/",
                title=(r.title or r.snippet)[:200], text=r.snippet or r.title, author_username=author,
                like_count=likes, published_at=published, extra=extra,
            )
        m = _LI_POST.match(r.url)
        if not m:
            return None
        url = m.group(0)
        return PostCandidate(
            platform="linkedin", post_id=url, url=url,
            title=(r.title or r.snippet)[:200], text=r.snippet or r.title, author_username=_handle(r.source),
            like_count=likes, published_at=published, extra=extra,
        )

    # ---- discovery -----------------------------------------------------------------
    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        found: Dict[str, PostCandidate] = {}
        searched = 0
        last_error: Optional[BrightDataSerpError] = None
        for q in self._queries(plan):
            start = 0
            for _ in range(MAX_PAGES):
                if len(found) >= limit:
                    return list(found.values())
                try:
                    page = await self.search.search(q["q"] or "", start=start, tbs=q["tbs"])
                except CollectorFatalError:
                    raise
                except BrightDataSerpError as exc:
                    logger.warning("SERP search failed (%s): %s", q["q"], str(exc)[:160])
                    last_error = exc
                    break
                searched += 1
                for r in page.results:
                    cand = self._candidate(r)
                    if cand and cand.url not in found:
                        found[cand.url] = cand
                if not page.next_start or not page.results:
                    break
                start = page.next_start
        if last_error is not None and not searched:
            raise last_error  # every search failed: that is an error, not "no posts"
        return list(found.values())

    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        return []  # a search engine does not return comments
