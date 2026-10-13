"""SocialCrawl REST backend: LinkedIn, X, Reddit and Instagram behind one client.

Response shape (envelope with `credits_used` / `credits_remaining`):
  search   -> data.items[].post {id, url, content.text, author{id,username,name},
                                 engagement|metrics{likes,comments|replies}, published_at}
  comments -> data.items[].comment|data|item {content.text|text, author{...}, metrics.likes, created_at}

The LinkedIn shape is verified. X / Reddit / Instagram use the same parser but were not
verified live (the account had 0 credits when this was written), so treat them as best effort:
nothing is ever invented - an unparseable response yields no rows.
"""

import logging
from typing import Any, Dict, List, Optional

from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.collectors.metered import MeteredMixin
from server.collection.ledger import ProviderLedger
from server.collection.models import CommentRow, PostCandidate, QueryPlan
from server.providers.socialcrawl.client import (
    SocialCrawlAuthenticationError,
    SocialCrawlClient,
    SocialCrawlError,
    SocialCrawlRateLimitError,
)

logger = logging.getLogger("mcp_server.collection.socialcrawl")

SEARCH_TTL = 6 * 3600
COMMENTS_TTL = 24 * 3600
MAX_PAGES = 3

SUPPORTED = ("linkedin", "x", "reddit", "instagram")


def _items(payload: Any) -> List[Dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else data
    return [i for i in (items or []) if isinstance(i, dict)]


def _text_of(node: Dict[str, Any]) -> str:
    content = node.get("content")
    text = content.get("text") if isinstance(content, dict) else None
    return (text or node.get("text") or "").strip()


def parse_post(platform: str, item: Dict[str, Any]) -> Optional[PostCandidate]:
    post = item.get("post") if isinstance(item.get("post"), dict) else item
    url = post.get("url")
    if not url:
        return None
    metrics = post.get("engagement") or post.get("metrics") or {}
    count: Optional[int] = None
    for key in ("comments", "replies", "comment_count"):
        if metrics.get(key) is not None:
            count = int(metrics[key] or 0)
            break
    if count == 0:  # nothing to harvest: never pay to open it
        return None
    author = post.get("author") or {}
    text = _text_of(post)
    return PostCandidate(
        platform=platform,
        post_id=str(post.get("id") or url),
        url=url,
        title=text[:200],
        text=text[:1500],
        author_username=author.get("username") or author.get("name"),
        author_id=str(author["id"]) if author.get("id") else None,
        comment_count=count,
        like_count=int(metrics["likes"]) if metrics.get("likes") is not None else None,
        published_at=post.get("published_at"),
    )


def parse_comment(platform: str, item: Dict[str, Any], post_url: str, provider: str) -> Optional[CommentRow]:
    node = item.get("comment") or item.get("data") or item
    text = _text_of(node)
    if not text:
        return None
    author = node.get("author") or {}
    return CommentRow(
        platform=platform,
        username=(author.get("username") or author.get("name") or "").strip(),
        user_id=str(author["id"]) if author.get("id") else None,
        comment=text,
        likes=int((node.get("metrics") or {}).get("likes") or 0),
        created_at=node.get("created_at"),
        post_url=post_url,
        provider=provider,
        comment_id=str(node["id"]) if node.get("id") else None,
        parent_id=str(node["parent_id"]) if node.get("parent_id") else None,
    )


class SocialCrawlBackend(MeteredMixin, PlatformCollector):
    provider = "socialcrawl"
    batch_size = 5
    concurrency = 2

    SEARCH_QUERIES = 2

    def __init__(
        self,
        platform: str,
        client: Optional[SocialCrawlClient] = None,
        ledger: Optional[ProviderLedger] = None,
    ):
        if platform not in SUPPORTED:
            raise ValueError(f"SocialCrawl backend does not support {platform}")
        self.platform = platform
        self._client = client
        self._ledger = ledger
        self.credits_used = 0.0

    @property
    def client(self) -> SocialCrawlClient:
        if self._client is None:
            self._client = SocialCrawlClient()
        return self._client

    def is_available(self) -> bool:
        return self.client.is_configured and not self.blocked_reason()

    def unavailable_reason(self) -> str:
        if self.client.is_configured:
            return self.blocked_reason() or "SocialCrawl is not usable right now"
        return "SOCIALCRAWL_API_KEY is not set"

    def usage(self) -> Dict[str, Any]:
        return {"credits_used": self.credits_used, "credits_remaining": self.client.last_credits_remaining}

    @staticmethod
    def _map_error(exc: Exception) -> Optional[Exception]:
        msg = str(exc)
        if isinstance(exc, SocialCrawlAuthenticationError):
            return CollectorFatalError(f"SocialCrawl rejected the API key: {msg[:160]}")
        if isinstance(exc, SocialCrawlRateLimitError):
            return CollectorFatalError(f"SocialCrawl rate limit: {msg[:160]}")
        if isinstance(exc, SocialCrawlError) and ("(402)" in msg or "INSUFFICIENT_CREDITS" in msg):
            return CollectorFatalError("SocialCrawl has no credits left (HTTP 402)")
        return None

    async def _call(self, name: str, key: List[Any], action: str, ttl: float, **kwargs: Any) -> Dict[str, Any]:
        fn = getattr(self.client, name)

        def _charged(payload: Any) -> float:
            used = payload.get("credits_used") if isinstance(payload, dict) else None
            return float(used) if isinstance(used, (int, float)) else 1.0

        return await self._metered([name, *key], lambda: fn(**kwargs), action, ttl, _charged, self._map_error)

    # ---- discovery -----------------------------------------------------------------
    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        n = max(5, min(20, limit))
        if self.platform == "instagram":
            tags = plan.hashtags[:1] or ["".join(plan.topic.lower().split())]
            searches = [("search_instagram_hashtag", {"hashtag": t, "limit": n}) for t in tags]
        else:
            method = {"linkedin": "search_linkedin_posts", "x": "search_tweets", "reddit": "search_reddit"}[self.platform]
            queries = ([plan.topic] + plan.keywords)[: self.SEARCH_QUERIES]
            searches = [(method, {"query": q, "limit": n}) for q in dict.fromkeys(queries)]

        found: Dict[str, PostCandidate] = {}
        for name, kwargs in searches:
            if len(found) >= limit:
                break
            try:
                payload = await self._call(name, [f"{k}={kwargs[k]}" for k in sorted(kwargs)], "search", SEARCH_TTL, **kwargs)
            except CollectorFatalError:
                raise
            except SocialCrawlError as exc:
                logger.warning("SocialCrawl %s failed: %s", name, str(exc)[:160])
                continue
            for item in _items(payload):
                cand = parse_post(self.platform, item)
                if cand and cand.url not in found:
                    found[cand.url] = cand
        return list(found.values())

    # ---- comments ------------------------------------------------------------------
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        method = {
            "linkedin": "get_linkedin_comments",
            "x": "get_tweet_replies",
            "reddit": "get_reddit_comments",
            "instagram": "get_instagram_comments",
        }[self.platform]
        url_arg = "tweet_url" if self.platform == "x" else "post_url"

        rows: List[CommentRow] = []
        cursor: Optional[str] = None
        for _ in range(MAX_PAGES):
            kwargs: Dict[str, Any] = {url_arg: post.url}
            if cursor:
                kwargs["cursor"] = cursor
            payload = await self._call(method, [post.url, cursor or ""], "comments", COMMENTS_TTL, **kwargs)
            for item in _items(payload):
                row = parse_comment(self.platform, item, post.url, self.provider)
                if row:
                    rows.append(row)
            pagination = (payload.get("pagination") or {}) if isinstance(payload, dict) else {}
            cursor = pagination.get("cursor") or (payload.get("next_cursor") if isinstance(payload, dict) else None)
            if len(rows) >= max_comments or not cursor:
                break
        return rows[:max_comments]
