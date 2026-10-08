"""Reddit provider for the generic social tools, backed by rdt-cli (replaces the old opencli provider)."""

import datetime
import logging
import re
from typing import Any, List, Optional

from server.collection.collectors.reddit import SITE, RedditCollector
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

logger = logging.getLogger("mcp_server.providers.social.reddit")


def _post_id(url_or_id: str) -> str:
    match = re.search(r"/comments/([0-9a-z]+)", url_or_id)
    return match.group(1) if match else url_or_id.strip().removeprefix("t3_")


class RedditSocialProvider(SocialDataProvider):
    """Reddit search + comments through rdt-cli (cookie auth via REDDIT_SESSION)."""

    platform_name = "reddit"
    provider_name = "rdt-cli"

    def __init__(self, collector: Optional[RedditCollector] = None):
        self.collector = collector or RedditCollector()

    def is_available(self) -> bool:
        return self.collector.is_available()

    async def search_content(self, query: str, limit: int = 10, **kwargs: Any) -> List[NormalizedSocialRecord]:
        if not self.is_available():
            logger.warning("rdt-cli / REDDIT_SESSION not available, cannot search reddit")
            return []
        raw = await self.collector._search([query, "-n", str(max(1, min(limit, 100))), "--sort", "relevance", "--time", "year"])
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        records: List[NormalizedSocialRecord] = []
        for d in raw[:limit]:
            cand: Optional[PostCandidate] = self.collector._candidate(d)
            if cand is None:
                continue
            records.append(
                NormalizedSocialRecord(
                    record_id=f"reddit:{cand.post_id}",
                    platform="reddit",
                    content_type="post",
                    source_url=cand.url,
                    content_id=cand.post_id,
                    published_at=cand.published_at,
                    author=SocialAuthor(username=cand.author_username, user_id=cand.author_id,
                                        display_name=cand.author_username),
                    content=SocialContent(title=cand.title, text=cand.text),
                    engagement=SocialEngagement(likes=cand.like_count, comments=cand.comment_count),
                    metadata=ProvenanceMetadata(
                        source_platform="reddit", source_provider=self.provider_name, backend_tool="rdt-cli",
                        fetched_at=now, source_url=cand.url,
                        provider_metadata={"subreddit": cand.extra.get("subreddit") or ""},
                    ),
                )
            )
        return records

    async def get_content(self, content_url_or_id: str) -> Optional[NormalizedSocialRecord]:
        return None

    async def get_comments(self, content_url_or_id: str, limit: int = 20) -> List[SocialInteraction]:
        if not self.is_available():
            return []
        pid = _post_id(content_url_or_id)
        post = PostCandidate(platform="reddit", post_id=pid, url=f"{SITE}/comments/{pid}/")
        try:
            rows = await self.collector.fetch_post_comments(post, limit)
        except Exception as exc:
            logger.error("rdt read failed for %s: %s", pid, exc)
            return []
        return [
            SocialInteraction(
                type="comment", text=r.comment, likes=r.likes, created_at=r.created_at,
                author=SocialAuthor(username=r.username, user_id=r.user_id, display_name=r.username),
            )
            for r in rows[:limit]
        ]

    async def get_profile(self, identifier: str) -> Optional[SocialAuthor]:
        user = identifier.replace("u/", "").strip()
        return SocialAuthor(username=user, profile_url=f"{SITE}/user/{user}")
