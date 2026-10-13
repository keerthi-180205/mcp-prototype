"""Platform collector interface used by the adaptive harvester."""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List

from server.collection.models import CollectionLimits, CommentRow, PostCandidate, QueryPlan


class CollectorFatalError(Exception):
    """Unrecoverable platform problem (bad credentials, exhausted credits, blocked)."""


class PlatformCollector(ABC):
    platform: str
    # Max posts fetched together in one harvesting step (Apify sends many URLs in a single run).
    batch_size: int = 1
    # Posts fetched concurrently inside a batch for CLI-based collectors.
    concurrency: int = 1

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return f"{self.platform} collector is not configured"

    def budget_exhausted(self) -> bool:
        return False

    def configure(self, limits: CollectionLimits) -> None:
        """Receive per-query limits (used by Apify hard caps)."""

    @abstractmethod
    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        """Return candidate posts (unranked) for the plan."""

    @abstractmethod
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        """Fetch up to ~max_comments raw comments for a single post."""

    async def fetch_comments(
        self, posts: List[PostCandidate], per_post_limit: Dict[str, int]
    ) -> Dict[str, List[CommentRow]]:
        """Fetch comments for several posts (default: bounded-concurrency single-post fetches).

        A failure for one post must not discard the others; it is simply absent from the result.
        A CollectorFatalError is re-raised.
        """
        sem = asyncio.Semaphore(max(1, self.concurrency))
        results: Dict[str, List[CommentRow]] = {}
        errors: List[Exception] = []

        async def _one(post: PostCandidate) -> None:
            async with sem:
                try:
                    results[post.url] = await self.fetch_post_comments(
                        post, per_post_limit.get(post.url, 100)
                    )
                except CollectorFatalError:
                    raise
                except Exception as exc:
                    errors.append(exc)

        await asyncio.gather(*[_one(p) for p in posts])
        if not results and errors:
            raise errors[0]
        return results
