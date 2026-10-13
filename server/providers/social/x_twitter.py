"""X / Twitter provider for the generic social tools, backed by twitter-cli."""

import datetime
import logging
import re
from typing import Any, List, Optional

from server.collection.collectors.x import XCollector
from server.collection.models import PostCandidate
from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialInteraction,
)
from server.providers.social.base import SocialDataProvider

logger = logging.getLogger("mcp_server.providers.social.x")


def _tweet_id(url_or_id: str) -> str:
    match = re.search(r"status/(\d+)", url_or_id)
    return match.group(1) if match else url_or_id.strip()


class XTwitterSocialProvider(SocialDataProvider):
    platform_name = "x"
    provider_name = "twitter-cli"

    def __init__(self, collector: Optional[XCollector] = None):
        self.collector = collector or XCollector()

    def is_available(self) -> bool:
        return self.collector.is_available()

    async def search_content(self, query: str, limit: int = 10, **kwargs: Any) -> List[NormalizedSocialRecord]:
        if not self.is_available():
            logger.warning("twitter credentials/syndication not available, cannot search X")
            return []
        from server.collection.models import QueryPlan
        plan = QueryPlan(topic=query, keywords=[query])
        candidates = await self.collector.discover(plan, limit=max(1, min(limit, 50)))
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        records: List[NormalizedSocialRecord] = []
        for cand in candidates[:limit]:
            records.append(
                NormalizedSocialRecord(
                    record_id=f"x:{cand.post_id}",
                    platform="x",
                    content_type="tweet",
                    source_url=cand.url,
                    content_id=cand.post_id,
                    published_at=cand.published_at,
                    author=SocialAuthor(
                        username=cand.author_username or "x_user",
                        user_id=cand.author_id or "x_user",
                        display_name=cand.author_username or "X User",
                    ),
                    content=SocialContent(text=cand.text or cand.title),
                    engagement=SocialEngagement(
                        likes=cand.like_count or 0,
                        comments=cand.comment_count or 0,
                        views=cand.view_count or 0,
                    ),
                    metadata=ProvenanceMetadata(
                        source_platform="x",
                        source_provider=self.provider_name,
                        backend_tool="twitter-search",
                        fetched_at=now,
                        source_url=cand.url,
                    ),
                )
            )
        return records

    async def get_content(self, content_url_or_id: str) -> Optional[NormalizedSocialRecord]:
        return None

    async def get_comments(self, content_url_or_id: str, limit: int = 20) -> List[SocialInteraction]:
        if not self.is_available():
            return []
        tid = _tweet_id(content_url_or_id)
        post = PostCandidate(platform="x", post_id=tid, url=f"https://x.com/i/status/{tid}")
        try:
            rows = await self.collector.fetch_post_comments(post, limit)
        except Exception as exc:
            logger.error("twitter tweet failed for %s: %s", tid, exc)
            return []
        return [
            SocialInteraction(type="reply", text=r.comment, likes=r.likes, created_at=r.created_at,
                              author=SocialAuthor(username=r.username, user_id=r.user_id, display_name=r.username))
            for r in rows[:limit]
        ]

    async def get_profile(self, identifier: str) -> Optional[SocialAuthor]:
        handle = identifier.replace("@", "").strip()
        return SocialAuthor(username=handle, profile_url=f"https://x.com/{handle}")
