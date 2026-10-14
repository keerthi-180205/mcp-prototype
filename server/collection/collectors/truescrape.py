"""TrueScrape REST backend (1 credit per call, cache hits and failed/empty calls are free).

Verified against the live API (see tests for recorded samples):
  reddit     discover (/v1/reddit/search) + comments (/v1/reddit/post/comments, includes parentId)
  instagram  comments only (/v1/instagram/post-comments, ~15 comments per credit, cursor paging).
             Its discovery endpoints answer 502 "upstream_blocked" (they need residential proxies),
             so discovery is left to another provider in the chain.
"""

import asyncio
import logging
import math
from typing import Any, Dict, List, Optional

from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.collectors.metered import MeteredMixin
from server.collection.ledger import ProviderLedger
from server.collection.models import CommentRow, PostCandidate, QueryPlan
from server.providers.truescrape.client import (
    TrueScrapeAuthenticationError,
    TrueScrapeClient,
    TrueScrapeError,
    TrueScrapeRateLimitError,
)

logger = logging.getLogger("mcp_server.collection.truescrape")

REMOVED = {"[deleted]", "[removed]"}
BOT_AUTHORS = {"automoderator"}
SEARCH_TTL = 6 * 3600       # search results go stale quickly
COMMENTS_TTL = 24 * 3600
PROFILE_TTL = 7 * 24 * 3600  # bios and follower counts change slowly
POST_TTL = 6 * 3600
LIST_TTL = 3600
# Instagram pages hold ~15 comments for 1 credit. The page budget grows with the number requested
# (a 500-comment target needs ~35 pages) but never beyond a hard ceiling.
MIN_INSTAGRAM_PAGES = 8
MAX_INSTAGRAM_PAGES = 45
COMMENTS_PER_PAGE = 12      # conservative: plan for fewer comments per page than the ~15 usually returned
GRID_PAGE_SIZE = 12
MAX_GRID_PAGES = 12

CAPABILITIES = {
    "reddit": {"discover": True, "comments": True},
    "instagram": {"discover": False, "comments": True},
}


def _items(payload: Any) -> List[Dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else data
    return [i for i in (items or []) if isinstance(i, dict)]


def unified_comment_row(item: Dict[str, Any], platform: str, post_url: str, provider: str) -> Optional[CommentRow]:
    """Map a TrueScrape unified comment (same schema on every platform) to a CommentRow."""
    text = (item.get("text") or "").strip()
    handle = (item.get("authorHandle") or "").strip()
    if not text or text in REMOVED or handle.lower() in REMOVED or handle.lower() in BOT_AUTHORS:
        return None
    if item.get("isAuthorReply"):  # the post creator's own replies are not "commenters"
        return None
    return CommentRow(
        platform=platform,
        username=handle,
        user_id=str(item["authorId"]) if item.get("authorId") else None,
        comment=text,
        likes=int(item.get("likeCount") or 0),
        created_at=item.get("publishedAt"),
        post_url=post_url,
        provider=provider,
        comment_id=str(item["id"]) if item.get("id") else None,
        parent_id=str(item["parentId"]) if item.get("parentId") else None,
    )


def _post_facts(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The few fields of a unified post object that the audience feature needs."""
    url = item.get("url")
    if not url:
        return None
    count = item.get("commentCount")
    return {
        "post_id": str(item["id"]) if item.get("id") else url.rstrip("/").rsplit("/", 1)[-1],
        "url": url,
        "author_handle": (item.get("authorHandle") or "").lstrip("@").strip(),
        "caption": (item.get("text") or item.get("title") or "")[:500],
        "comment_count": int(count) if isinstance(count, (int, float)) else None,   # None = not exposed, not zero
        "published_at": item.get("publishedAt"),
    }


class TrueScrapeBackend(MeteredMixin, PlatformCollector):
    provider = "truescrape"
    batch_size = 3
    concurrency = 2

    SEARCH_KEYWORDS = 3
    SEARCH_SUBREDDITS = 3

    def __init__(
        self,
        platform: str,
        client: Optional[TrueScrapeClient] = None,
        ledger: Optional[ProviderLedger] = None,
    ):
        if platform not in CAPABILITIES:
            raise ValueError(f"TrueScrape backend does not support {platform}")
        self.platform = platform
        self.can_discover = CAPABILITIES[platform]["discover"]
        self.can_comments = CAPABILITIES[platform]["comments"]
        self._client = client
        self._ledger = ledger
        self.credits_used = 0.0

    @property
    def client(self) -> TrueScrapeClient:
        if self._client is None:
            self._client = TrueScrapeClient()
        return self._client

    def is_available(self) -> bool:
        return self.client.is_configured and not self.blocked_reason()

    def unavailable_reason(self) -> str:
        if self.client.is_configured:
            return self.blocked_reason() or "TrueScrape is not usable right now"
        return "TRUESCRAPE_API_KEY is not set"

    def usage(self) -> Dict[str, Any]:
        return {"credits_used": self.credits_used}

    # ---- one metered, cached call --------------------------------------------------
    @staticmethod
    def _map_error(exc: Exception) -> Optional[Exception]:
        msg = str(exc)
        if isinstance(exc, TrueScrapeAuthenticationError):
            return CollectorFatalError(f"TrueScrape rejected the API key: {msg[:160]}")
        if isinstance(exc, TrueScrapeRateLimitError):
            return CollectorFatalError(f"TrueScrape rate/credit limit: {msg[:160]}")
        if isinstance(exc, TrueScrapeError) and ("HTTP 402" in msg or "credit" in msg.lower()):
            return CollectorFatalError(f"TrueScrape out of credits: {msg[:160]}")
        return None

    async def _call(self, endpoint: str, params: Dict[str, Any], action: str, ttl: float) -> Dict[str, Any]:
        return await self._metered(
            [endpoint, *[f"{k}={params[k]}" for k in sorted(params)]],
            lambda: self.client.get(endpoint, params),
            action,
            ttl,
            lambda payload: float(((payload or {}).get("meta") or {}).get("creditsCharged") or 0),
            self._map_error,
        )

    # ---- discovery (reddit) --------------------------------------------------------
    @staticmethod
    def _reddit_candidate(item: Dict[str, Any]) -> Optional[PostCandidate]:
        count = int(item.get("commentCount") or 0)
        if not item.get("id") or not item.get("url") or count <= 0:
            return None
        return PostCandidate(
            platform="reddit",
            post_id=str(item["id"]),
            url=item["url"],
            title=item.get("title") or "",
            text=(item.get("text") or "")[:1500],
            author_username=item.get("authorHandle"),
            author_id=str(item["authorId"]) if item.get("authorId") else None,
            comment_count=count,
            like_count=item.get("likeCount"),
            published_at=item.get("publishedAt"),
        )

    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        if not self.can_discover:
            return []
        keywords = plan.keywords[: self.SEARCH_KEYWORDS] or [plan.topic]
        jobs: List[Dict[str, Any]] = [
            {"query": kw, "sort": "relevance", "timeframe": "year", "limit": 50} for kw in keywords
        ]
        jobs += [
            {"query": keywords[0], "subreddit": sub, "sort": "top", "timeframe": "month", "limit": 25}
            for sub in plan.subreddits[: self.SEARCH_SUBREDDITS]
        ]
        sem = asyncio.Semaphore(self.concurrency)

        async def _run(params: Dict[str, Any]) -> List[Dict[str, Any]]:
            async with sem:
                try:
                    return _items(await self._call("/v1/reddit/search", params, "search", SEARCH_TTL))
                except CollectorFatalError:
                    raise
                except TrueScrapeError as exc:
                    logger.warning("TrueScrape reddit search failed: %s", str(exc)[:160])
                    return []

        found: Dict[str, PostCandidate] = {}
        for batch in await asyncio.gather(*[_run(j) for j in jobs]):
            for item in batch:
                cand = self._reddit_candidate(item)
                if cand and cand.post_id not in found:
                    found[cand.post_id] = cand
        return list(found.values())

    # ---- profiles ------------------------------------------------------------------
    async def instagram_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        """Public profile facts for one Instagram handle (bio, links, followers): 1 credit, cached for a week."""
        if self.platform != "instagram":
            raise ValueError("instagram_profile is only available on the instagram backend")
        handle = handle.lstrip("@").strip()
        payload = await self._call("/v1/instagram/profile", {"handle": handle}, "profile", PROFILE_TTL)
        data = (payload or {}).get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data:
            return None
        links = [(x if isinstance(x, str) else (x or {}).get("url")) for x in (data.get("externalLinks") or [])]
        return {
            "handle": data.get("handle") or handle,
            "display_name": data.get("displayName") or "",
            "bio": data.get("bio") or "",
            "external_links": [l for l in links if l],
            "followers": data.get("followerCount"),
            "is_business": data.get("isBusiness"),
            "category": data.get("category"),
            "is_private": bool(data.get("isPrivate")),
            "url": data.get("url") or f"https://www.instagram.com/{handle}/",
        }

    async def instagram_post(self, url: str) -> Optional[Dict[str, Any]]:
        """Facts about one post (owner, caption, counts, date): 1 credit, cached for 6 hours."""
        if self.platform != "instagram":
            raise ValueError("instagram_post is only available on the instagram backend")
        payload = await self._call("/v1/instagram/post", {"url": url}, "post", POST_TTL)
        data = (payload or {}).get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data = next((i for i in data["items"] if isinstance(i, dict)), None)
        return _post_facts(data) if isinstance(data, dict) and data else None

    async def instagram_user_posts(self, handle: str, max_posts: int) -> List[Dict[str, Any]]:
        """Newest posts of one profile (12 per credit). Collab / tagged posts owned by someone else
        are returned too: callers decide by each post's `author_handle`."""
        if self.platform != "instagram":
            raise ValueError("instagram_user_posts is only available on the instagram backend")
        handle = handle.lstrip("@").strip()
        found: Dict[str, Dict[str, Any]] = {}
        cursor: Optional[str] = None
        for _ in range(min(MAX_GRID_PAGES, max(1, math.ceil(max_posts / GRID_PAGE_SIZE)) + 1)):
            params: Dict[str, Any] = {"handle": handle}
            if cursor:
                params["cursor"] = cursor
            payload = await self._call("/v1/instagram/user-posts", params, "user_posts", LIST_TTL)
            for item in _items(payload):
                facts = _post_facts(item)
                if facts and facts["url"] not in found:
                    found[facts["url"]] = facts
            pagination = (payload.get("pagination") if isinstance(payload, dict) else None) or {}
            cursor = pagination.get("cursor")
            if len(found) >= max_posts or not pagination.get("hasMore") or not cursor:
                break
        return list(found.values())[:max_posts]

    # ---- comments ------------------------------------------------------------------
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        if not self.can_comments:
            return []
        if self.platform == "reddit":
            return await self._reddit_comments(post, max_comments)
        return await self._instagram_comments(post, max_comments)

    async def _reddit_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        params = {"url": post.url, "sort": "top", "limit": max(1, int(max_comments))}
        payload = await self._call("/v1/reddit/post/comments", params, "comments", COMMENTS_TTL)
        rows = [unified_comment_row(i, "reddit", post.url, self.provider) for i in _items(payload)]
        return [r for r in rows if r]

    async def _instagram_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        rows: List[CommentRow] = []
        cursor: Optional[str] = None
        pages = min(MAX_INSTAGRAM_PAGES, max(MIN_INSTAGRAM_PAGES, math.ceil(max_comments / COMMENTS_PER_PAGE) + 1))
        for page in range(pages):
            params: Dict[str, Any] = {"url": post.url, "count": 50}
            if cursor:
                params["cursor"] = cursor
            try:
                payload = await self._call("/v1/instagram/post-comments", params, "comments", COMMENTS_TTL)
            except CollectorFatalError:
                if page == 0:
                    raise
                # Budget or credits ran out mid-post: keep the pages already paid for. The next call raises again
                # from page one, so the chain still switches this provider off.
                logger.warning("TrueScrape stopped after %d comments on %s; keeping them", len(rows), post.url)
                break
            rows += [r for r in (unified_comment_row(i, "instagram", post.url, self.provider) for i in _items(payload)) if r]
            pagination = payload.get("pagination") or {}
            cursor = pagination.get("cursor")
            if len(rows) >= max_comments or not pagination.get("hasMore") or not cursor:
                break
        return rows[:max_comments]
