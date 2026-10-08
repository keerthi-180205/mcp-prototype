"""Configurable adapters for LinkedIn and Facebook."""

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
