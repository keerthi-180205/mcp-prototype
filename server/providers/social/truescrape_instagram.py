"""Instagram social data provider implementation using TrueScrape capability engine."""

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
from server.providers.truescrape.instagram import TrueScrapeInstagramProvider

logger = logging.getLogger("mcp_server.providers.social.truescrape_instagram")


class TrueScrapeInstagramSocialProvider(SocialDataProvider):
    """Instagram data acquisition provider using TrueScrape high-performance REST API."""

    platform_name = "instagram"
    provider_name = "truescrape"

    def __init__(self, provider: Optional[TrueScrapeInstagramProvider] = None):
        self.provider = provider or TrueScrapeInstagramProvider()
        self.settings = get_settings()

    def is_available(self) -> bool:
        """Available if TRUESCRAPE_API_KEY is configured."""
        return bool(self.settings.truescrape_api_key)

    def _extract_shortcode(self, url_or_id: str) -> str:
        match = re.search(r"/(?:p|reel|reels)/([A-Za-z0-9_-]+)", url_or_id)
        if match:
            return match.group(1)
        return url_or_id.strip().strip("/")

    async def search_content(
        self, query: str, limit: int = 20, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        """Search public Instagram posts/reels for a topic tag or query using TrueScrape."""
        if not self.is_available():
            logger.warning("TrueScrapeInstagramSocialProvider search skipped: TRUESCRAPE_API_KEY not configured")
            return []

        raw_posts = await self.provider.search_posts_or_reels(query=query, max_results=limit)
        records: List[NormalizedSocialRecord] = []
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for post in raw_posts:
            shortcode = post.get("shortCode") or post.get("id") or self._extract_shortcode(post.get("url", ""))
            author_data = post.get("author") or {}
            caption = post.get("caption") or post.get("text") or ""
            url = post.get("url") or f"https://www.instagram.com/reel/{shortcode}/"

            record = NormalizedSocialRecord(
                record_id=f"instagram:{shortcode}",
                platform="instagram",
                content_type=post.get("type") or "reel",
                source_url=url,
                content_id=str(shortcode),
                published_at=post.get("timestamp"),
                author=SocialAuthor(
                    username=author_data.get("username") or post.get("ownerUsername"),
                    user_id=str(author_data.get("id") or post.get("ownerId") or ""),
                    display_name=author_data.get("name") or post.get("ownerFullName"),
                    profile_url=f"https://www.instagram.com/{author_data.get('username') or post.get('ownerUsername')}/" if (author_data.get("username") or post.get("ownerUsername")) else None,
                ),
                content=SocialContent(
                    caption=caption,
                    text=caption,
                    tags=[w.strip("#") for w in caption.split() if w.startswith("#")],
                ),
                engagement=SocialEngagement(
                    likes=post.get("likesCount") or 0,
                    comments=post.get("commentsCount") or 0,
                    views=post.get("videoViews") or 0,
                ),
                interactions=[],
                metadata=ProvenanceMetadata(
                    source_platform="instagram",
                    source_provider="truescrape",
                    backend_tool="truescrape/v1/instagram",
                    fetched_at=now_iso,
                    source_url=url,
                ),
            )
            records.append(record)

        return records

    async def get_content(
        self, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Fetch single post details and public comments using TrueScrape."""
        if not self.is_available():
            return None

        url = content_url_or_id
        if not url.startswith("http"):
            url = f"https://www.instagram.com/reel/{content_url_or_id}/"

        shortcode = self._extract_shortcode(url)
        detail = await self.provider.get_post_details(url)
        comments = await self.get_comments(url, limit=20)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if detail:
            author_data = detail.get("author") or {}
            caption = detail.get("caption") or detail.get("text") or ""
            return NormalizedSocialRecord(
                record_id=f"instagram:{shortcode}",
                platform="instagram",
                content_type=detail.get("type") or "reel",
                source_url=url,
                content_id=str(shortcode),
                published_at=detail.get("timestamp"),
                author=SocialAuthor(
                    username=author_data.get("username") or detail.get("ownerUsername"),
                    user_id=str(author_data.get("id") or detail.get("ownerId") or ""),
                    display_name=author_data.get("name") or detail.get("ownerFullName"),
                    profile_url=f"https://www.instagram.com/{author_data.get('username') or detail.get('ownerUsername')}/" if (author_data.get("username") or detail.get("ownerUsername")) else None,
                ),
                content=SocialContent(
                    caption=caption,
                    text=caption,
                    tags=[w.strip("#") for w in caption.split() if w.startswith("#")],
                ),
                engagement=SocialEngagement(
                    likes=detail.get("likesCount") or 0,
                    comments=detail.get("commentsCount") or len(comments),
                    views=detail.get("videoViews") or 0,
                ),
                interactions=comments,
                metadata=ProvenanceMetadata(
                    source_platform="instagram",
                    source_provider="truescrape",
                    backend_tool="truescrape/v1/instagram",
                    fetched_at=now_iso,
                    source_url=url,
                ),
            )

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
                source_provider="truescrape",
                backend_tool="truescrape/v1/instagram",
                fetched_at=now_iso,
                source_url=url,
            ),
        )

    async def get_comments(
        self, content_url_or_id: str, limit: int = 20
    ) -> List[SocialInteraction]:
        """Fetch public comments for a post or reel URL via TrueScrape."""
        if not self.is_available():
            return []

        url = content_url_or_id
        if not url.startswith("http"):
            url = f"https://www.instagram.com/reel/{content_url_or_id}/"

        raw_comments = await self.provider.get_post_comments(post_url=url, max_comments=limit)
        interactions: List[SocialInteraction] = []

        for c in raw_comments:
            user_data = c.get("user") or {}
            uid = user_data.get("id") or c.get("authorId")
            uname = (
                user_data.get("username")
                or user_data.get("handle")
                or c.get("authorHandle")
                or c.get("username")
                or user_data.get("name")
                or (f"user_{uid}" if uid else "anonymous")
            ).strip().lstrip("@")
            interactions.append(
                SocialInteraction(
                    interaction_id=str(c.get("comment_id") or c.get("id") or ""),
                    type="comment",
                    text=c.get("text") or "",
                    author=SocialAuthor(
                        username=uname,
                        user_id=str(uid) if uid else None,
                        display_name=user_data.get("name"),
                        profile_url=f"https://www.instagram.com/{uname}/" if uname and uname != "anonymous" else None,
                        profile_pic_url=user_data.get("profile_pic_url"),
                    ),
                    created_at=c.get("timestamp"),
                    likes=c.get("likesCount") or 0,
                )
            )

        return interactions

    async def get_profile(
        self, identifier: str
    ) -> Optional[SocialAuthor]:
        """Fetch public profile metadata via TrueScrape."""
        username = identifier.replace("@", "").strip().strip("/")
        if not self.is_available():
            return SocialAuthor(username=username, profile_url=f"https://www.instagram.com/{username}/")

        prof = await self.provider.get_profile(username)
        if prof:
            return SocialAuthor(
                user_id=prof.get("id"),
                username=prof.get("username") or username,
                display_name=prof.get("display_name"),
                bio=prof.get("bio"),
                profile_url=f"https://www.instagram.com/{username}/",
                profile_pic_url=prof.get("profile_picture_url"),
                followers=prof.get("followers_count"),
                following=prof.get("following_count"),
                is_verified=prof.get("is_verified", False),
            )

        return SocialAuthor(
            username=username,
            profile_url=f"https://www.instagram.com/{username}/",
        )
