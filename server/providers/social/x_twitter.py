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
            logger.warning("twitter-cli / credentials not available, cannot search X")
            return []
        raw = await self.collector._search(query, "top", max(1, min(limit, 100)))
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        records: List[NormalizedSocialRecord] = []
        for t in raw[:limit]:
            cand = self.collector._candidate(t)
            if cand is None:
                continue
            records.append(
                NormalizedSocialRecord(
                    record_id=f"x:{cand.post_id}",
                    platform="x",
                    content_type="tweet",
                    source_url=cand.url,
                    content_id=cand.post_id,
                    published_at=cand.published_at,
                    author=SocialAuthor(username=cand.author_username, user_id=cand.author_id,
                                        display_name=(t.get("author") or {}).get("name")),
                    content=SocialContent(text=cand.text),
                    engagement=SocialEngagement(likes=cand.like_count, comments=cand.comment_count,
                                                views=cand.view_count),
                    metadata=ProvenanceMetadata(source_platform="x", source_provider=self.provider_name,
                                                backend_tool="twitter-cli", fetched_at=now, source_url=cand.url),
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
