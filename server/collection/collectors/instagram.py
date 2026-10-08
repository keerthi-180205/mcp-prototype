"""Instagram collector: Apify actors with HARD per-query caps on comments and cost."""

import logging
import os
from typing import Any, Dict, List, Optional

from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.models import CollectionLimits, CommentRow, PostCandidate, QueryPlan
from server.providers.apify.client import (
    ApifyAuthenticationError,
    ApifyRateLimitError,
)
from server.providers.apify.instagram import ApifyInstagramProvider

logger = logging.getLogger("mcp_server.collection.instagram")

MAX_TAGS = 3
DISCOVERY_BUDGET_SHARE = 0.4


def _post_key(url: Optional[str]) -> str:
    return (url or "").split("?")[0].rstrip("/").lower()


class InstagramCollector(PlatformCollector):
    platform = "instagram"
    batch_size = 25  # posts per Actor run: one run is far cheaper than one run per post

    def __init__(self, provider: Optional[ApifyInstagramProvider] = None, token: Optional[str] = None):
        self._provider = provider
        self._token = token if token is not None else os.getenv("APIFY_API_TOKEN")
        # Cost model measured from real Apify run billing: pay-per-result, no per-run fee.
        self.price_result = float(os.getenv("APIFY_COST_PER_RESULT_USD", "0.0027"))  # instagram-scraper
        self.price_comment = float(os.getenv("APIFY_COST_PER_COMMENT_USD", "0.0026"))  # comment scraper
        self.cost_per_run = float(os.getenv("APIFY_COST_PER_RUN_USD", "0"))
        self.max_items = 1500
        self.max_cost = 0.5
        self.discovery_posts = 120
        self.items_used = 0
        self.spent_estimate = 0.0
        self.runs = 0

    @property
    def provider(self) -> ApifyInstagramProvider:
        if self._provider is None:
            self._provider = ApifyInstagramProvider()
        return self._provider

    def is_available(self) -> bool:
        return bool(self._token) or self._provider is not None

    def unavailable_reason(self) -> str:
        return "APIFY_API_TOKEN is not set"

    def configure(self, limits: CollectionLimits) -> None:
        self.max_items = limits.apify_max_comments_per_query
        self.max_cost = limits.apify_max_cost_usd
        self.discovery_posts = limits.instagram_discovery_posts

    # ---- budget --------------------------------------------------------------------
    def _remaining_cost(self) -> float:
        return self.max_cost - self.spent_estimate

    def _remaining_items(self) -> int:
        return self.max_items - self.items_used

    def _affordable(self, price: float) -> int:
        """How many items at `price` each still fit under both the item cap and the cost cap."""
        by_cost = int((self._remaining_cost() - self.cost_per_run) / price + 1e-9) if price > 0 else self._remaining_items()
        return max(0, min(self._remaining_items(), by_cost))

    def budget_exhausted(self) -> bool:
        return self._affordable(self.price_comment) < 1

    def _account(self, n_items: int, price: float) -> None:
        self.runs += 1
        self.items_used += n_items
        self.spent_estimate += self.cost_per_run + n_items * price

    def usage(self) -> Dict[str, Any]:
        return {
            "apify_runs": self.runs,
            "items_billed_estimate": self.items_used,
            "estimated_cost_usd": round(self.spent_estimate, 3),
            "cap_items": self.max_items,
            "cap_cost_usd": self.max_cost,
        }

    @staticmethod
    def _fatal(exc: Exception) -> CollectorFatalError:
        return CollectorFatalError(f"Apify: {exc}")

    # ---- discovery -----------------------------------------------------------------
    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        tags = plan.hashtags[:MAX_TAGS] or ["".join(plan.topic.lower().split())]
        # Finding posts is billed per post too, and most recent posts have no comments yet:
        # never spend more than DISCOVERY_BUDGET_SHARE of the cost cap on discovery.
        by_budget = int(self.max_cost * DISCOVERY_BUDGET_SHARE / self.price_result) if self.price_result > 0 else self.discovery_posts
        total = min(self.discovery_posts, self.max_items, by_budget, self._affordable(self.price_result))
        if total < 1:
            return []
        tags = tags[: max(1, total)]
        per_tag = -(-total // len(tags))
        try:
            items = await self.provider.search_hashtags(
                tags,
                per_tag,
                max_items=total,
                max_total_charge_usd=max(0.01, min(self._remaining_cost(), total * self.price_result + 0.01)),
            )
        except (ApifyAuthenticationError, ApifyRateLimitError) as exc:
            raise self._fatal(exc) from exc
        self._account(len(items), self.price_result)

        out: Dict[str, PostCandidate] = {}
        for it in items:
            if not isinstance(it, dict) or it.get("error"):
                continue
            url = it.get("url") or (f"https://www.instagram.com/p/{it['shortCode']}/" if it.get("shortCode") else None)
            if not url:
                continue
            count = it.get("commentsCount")
            if not count:  # nothing to harvest -> never pay to open it
                continue
            caption = it.get("caption") or ""
            hashtags = " ".join(f"#{h}" for h in (it.get("hashtags") or []))
            out[_post_key(url)] = PostCandidate(
                platform="instagram",
                post_id=str(it.get("shortCode") or it.get("id") or url),
                url=url,
                title=caption[:200],
                text=f"{caption} {hashtags}"[:1500],
                author_username=it.get("ownerUsername"),
                author_id=str(it["ownerId"]) if it.get("ownerId") is not None else None,
                comment_count=int(count),
                like_count=it.get("likesCount"),
                view_count=it.get("videoViewCount") or it.get("videoPlayCount"),
                published_at=it.get("timestamp"),
            )
        return list(out.values())

    # ---- comments ------------------------------------------------------------------
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        return (await self.fetch_comments([post], {post.url: max_comments})).get(post.url, [])

    async def fetch_comments(
        self, posts: List[PostCandidate], per_post_limit: Dict[str, int]
    ) -> Dict[str, List[CommentRow]]:
        if not posts or self.budget_exhausted():
            return {}
        wanted = {p.url: per_post_limit.get(p.url, 50) for p in posts}
        max_items = min(sum(wanted.values()), self._affordable(self.price_comment))
        if max_items < 1:
            return {}
        try:
            items = await self.provider.get_comments_batch(
                [p.url for p in posts],
                max(wanted.values()),
                max_items=max_items,
                max_total_charge_usd=max(0.01, min(self._remaining_cost(), max_items * self.price_comment + 0.01)),
            )
        except (ApifyAuthenticationError, ApifyRateLimitError) as exc:
            raise self._fatal(exc) from exc
        self._account(len(items), self.price_comment)

        by_key = {_post_key(p.url): p.url for p in posts}
        results: Dict[str, List[CommentRow]] = {p.url: [] for p in posts}
        for it in items:
            if not isinstance(it, dict) or it.get("error"):
                continue
            url = by_key.get(_post_key(it.get("postUrl") or it.get("inputUrl")))
            if not url:
                continue
            results[url].extend(self._rows(it, url))
        return results

    @classmethod
    def _rows(cls, item: Dict[str, Any], post_url: str) -> List[CommentRow]:
        owner = item.get("owner") or {}
        uid = owner.get("id") or item.get("ownerId")
        rows = [
            CommentRow(
                platform="instagram",
                username=item.get("ownerUsername") or owner.get("username") or "",
                user_id=str(uid) if uid is not None else None,
                comment=item.get("text") or "",
                likes=int(item.get("likesCount") or 0),
                created_at=item.get("timestamp"),
                post_url=post_url,
            )
        ]
        replies = item.get("replies")
        if isinstance(replies, list):
            for reply in replies:
                if isinstance(reply, dict):
                    rows.extend(cls._rows({**reply, "replies": None}, post_url))
        return rows
