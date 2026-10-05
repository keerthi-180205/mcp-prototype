"""Instagram social data provider implementation using Apify capability layer."""

import datetime
import logging
import re
from typing import Any, Dict, List, Optional

from server.config import get_settings
from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialInteraction,
)
from server.providers.social.base import SocialDataProvider
from server.services.instagram import InstagramService

logger = logging.getLogger("mcp_server.providers.social.instagram")


class InstagramSocialProvider(SocialDataProvider):
    """Instagram data acquisition provider using Apify actors as the underlying capability engine."""

    platform_name = "instagram"
    provider_name = "apify"

    def __init__(self, service: Optional[InstagramService] = None):
        self.service = service or InstagramService()
        self.settings = get_settings()

    def is_available(self) -> bool:
        """Available if APIFY_API_TOKEN is configured."""
        return bool(self.settings.apify_api_token)

    def _extract_shortcode(self, url_or_id: str) -> str:
        match = re.search(r"/(?:p|reel|reels)/([A-Za-z0-9_-]+)", url_or_id)
        if match:
            return match.group(1)
        return url_or_id.strip().strip("/")

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        """Search public Instagram posts/reels for a topic tag or query."""
        if not self.is_available():
            logger.warning("InstagramSocialProvider search skipped: APIFY_API_TOKEN not configured")
            return []

        posts = await self.service.search_posts_or_reels(query=query, max_results=limit)
        records: List[NormalizedSocialRecord] = []

        now_iso = datetime.datetime.utcnow().isoformat() + "Z"

        for post in posts:
            shortcode = post.content_id or self._extract_shortcode(post.url)
            record_id = f"instagram:{shortcode}"
            record = NormalizedSocialRecord(
                record_id=record_id,
                platform="instagram",
                content_type=post.content_type or "reel",
                source_url=post.url,
                content_id=shortcode,
                published_at=post.created_at,
                author=SocialAuthor(
                    username=post.author.username if post.author else None,
                    user_id=post.author.id if post.author else None,
                    display_name=post.author.display_name if post.author else None,
                    profile_url=f"https://www.instagram.com/{post.author.username}/" if post.author and post.author.username else None,
                    is_verified=post.author.is_verified if post.author else False,
                    is_private=post.author.is_private if post.author else False,
                ),
                content=SocialContent(
                    caption=post.caption,
                    text=post.caption,
                    tags=[w.strip("#") for w in (post.caption or "").split() if w.startswith("#")],
                ),
                engagement=SocialEngagement(
                    likes=post.like_count,
                    comments=post.comment_count,
                    views=post.view_count,
                ),
                interactions=[],
                metadata=ProvenanceMetadata(
                    source_platform="instagram",
                    source_provider="apify",
                    backend_tool="apify/instagram-scraper",
                    fetched_at=now_iso,
                    source_url=post.url,
                ),
            )
            records.append(record)

        return records

    async def get_content(
        self, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Fetch single post info and public comments."""
        if not self.is_available():
            return None

        # Build clean direct URL
        url = content_url_or_id
        if not url.startswith("http"):
            url = f"https://www.instagram.com/reel/{content_url_or_id}/"

        shortcode = self._extract_shortcode(url)
        comments = await self.get_comments(url, limit=20)

        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        return NormalizedSocialRecord(
            record_id=f"instagram:{shortcode}",
            platform="instagram",
            content_type="reel" if "/reel/" in url else "post",
            source_url=url,
            content_id=shortcode,
            published_at=None,
            author=SocialAuthor(),
            content=SocialContent(),
            engagement=SocialEngagement(comments=len(comments)),
            interactions=comments,
            metadata=ProvenanceMetadata(
                source_platform="instagram",
                source_provider="apify",
                backend_tool="apify/instagram-comment-scraper",
                fetched_at=now_iso,
                source_url=url,
            ),
        )

    async def get_comments(
        self, content_url_or_id: str, limit: int = 20
    ) -> List[SocialInteraction]:
        """Fetch public comments for a post or reel URL."""
        if not self.is_available():
            return []

        url = content_url_or_id
        if not url.startswith("http"):
            url = f"https://www.instagram.com/reel/{content_url_or_id}/"

        result = await self.service.get_post_comments(post_url=url, max_comments=limit)
        interactions: List[SocialInteraction] = []

        for c in result.comments:
            interactions.append(
                SocialInteraction(
                    interaction_id=c.comment_id,
                    type="comment",
                    text=c.text or "",
                    author=SocialAuthor(
                        username=c.user.username if c.user else None,
                        user_id=c.user.id if c.user else None,
                        display_name=c.user.display_name if c.user else None,
                        profile_url=f"https://www.instagram.com/{c.user.username}/" if c.user and c.user.username else None,
                        is_verified=c.user.is_verified if c.user else False,
                        is_private=c.user.is_private if c.user else False,
                    ),
                    created_at=c.created_at,
                    likes=c.like_count,
                )
            )

        return interactions

    async def get_profile(
        self, identifier: str
    ) -> Optional[SocialAuthor]:
        """Fetch public profile metadata."""
        username = identifier.replace("@", "").strip().strip("/")
        return SocialAuthor(
            username=username,
            profile_url=f"https://www.instagram.com/{username}/",
        )
