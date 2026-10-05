"""Configurable adapters for Reddit, X/Twitter, LinkedIn, and Facebook."""

import logging
import os
import shutil
from typing import Any, Dict, List, Optional

from server.models import (
    NormalizedSocialRecord,
    SocialAuthor,
    SocialInteraction,
)
from server.providers.social.base import SocialDataProvider

logger = logging.getLogger("mcp_server.providers.social.stubs")


class RedditSocialProvider(SocialDataProvider):
    """Reddit public data provider (via rdt-cli, OpenCLI, or configured API)."""

    platform_name = "reddit"
    provider_name = "reddit_adapter"

    def is_available(self) -> bool:
        return bool(shutil.which("rdt-cli") or os.getenv("REDDIT_CLIENT_ID"))

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        logger.info("Reddit search for '%s' requested. Backend available: %s", query, self.is_available())
        return []

    async def get_content(self, content_url_or_id: str) -> Optional[NormalizedSocialRecord]:
        return None

    async def get_comments(self, content_url_or_id: str, limit: int = 20) -> List[SocialInteraction]:
        return []

    async def get_profile(self, identifier: str) -> Optional[SocialAuthor]:
        user = identifier.replace("u/", "").strip()
        return SocialAuthor(username=user, profile_url=f"https://www.reddit.com/user/{user}")


class XTwitterSocialProvider(SocialDataProvider):
    """X / Twitter public data provider (via twitter-cli or official API)."""

    platform_name = "x"
    provider_name = "x_adapter"

    def is_available(self) -> bool:
        return bool(shutil.which("twitter-cli") or os.getenv("TWITTER_BEARER_TOKEN"))

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        logger.info("X/Twitter search for '%s' requested. Backend available: %s", query, self.is_available())
        return []

    async def get_content(self, content_url_or_id: str) -> Optional[NormalizedSocialRecord]:
        return None

    async def get_comments(self, content_url_or_id: str, limit: int = 20) -> List[SocialInteraction]:
        return []

    async def get_profile(self, identifier: str) -> Optional[SocialAuthor]:
        handle = identifier.replace("@", "").strip()
        return SocialAuthor(username=handle, profile_url=f"https://x.com/{handle}")


class LinkedInSocialProvider(SocialDataProvider):
    """LinkedIn public pages and jobs provider."""

    platform_name = "linkedin"
    provider_name = "linkedin_adapter"

    def is_available(self) -> bool:
        return bool(os.getenv("LINKEDIN_ACCESS_TOKEN"))

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        return []

    async def get_content(self, content_url_or_id: str) -> Optional[NormalizedSocialRecord]:
        return None

    async def get_comments(self, content_url_or_id: str, limit: int = 20) -> List[SocialInteraction]:
        return []

    async def get_profile(self, identifier: str) -> Optional[SocialAuthor]:
        return SocialAuthor(username=identifier)


class FacebookSocialProvider(SocialDataProvider):
    """Facebook public pages provider."""

    platform_name = "facebook"
    provider_name = "facebook_adapter"

    def is_available(self) -> bool:
        return bool(os.getenv("FACEBOOK_ACCESS_TOKEN"))

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        return []

    async def get_content(self, content_url_or_id: str) -> Optional[NormalizedSocialRecord]:
        return None

    async def get_comments(self, content_url_or_id: str, limit: int = 20) -> List[SocialInteraction]:
        return []

    async def get_profile(self, identifier: str) -> Optional[SocialAuthor]:
        return SocialAuthor(username=identifier)
