"""TrueScrape REST backend (1 credit per call, cache hits and failed/empty calls are free).

Verified against the live API (see tests for recorded samples):
  reddit     discover (/v1/reddit/search) + comments (/v1/reddit/post/comments, includes parentId)
  instagram  comments only (/v1/instagram/post-comments, ~15 comments per credit, cursor paging).
             Its discovery endpoints answer 502 "upstream_blocked" (they need residential proxies),
             so discovery is left to another provider in the chain.
"""

import asyncio
import logging
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
MAX_INSTAGRAM_PAGES = 8     # hard stop on cursor paging (8 credits per post at most)

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
        for _ in range(MAX_INSTAGRAM_PAGES):
            params: Dict[str, Any] = {"url": post.url, "count": 50}
            if cursor:
                params["cursor"] = cursor
            payload = await self._call("/v1/instagram/post-comments", params, "comments", COMMENTS_TTL)
            rows += [r for r in (unified_comment_row(i, "instagram", post.url, self.provider) for i in _items(payload)) if r]
            pagination = payload.get("pagination") or {}
            cursor = pagination.get("cursor")
            if len(rows) >= max_comments or not pagination.get("hasMore") or not cursor:
                break
        return rows[:max_comments]
