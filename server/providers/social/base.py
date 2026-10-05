"""Base abstraction for social data providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from server.models import (
    NormalizedSocialRecord,
    SocialAuthor,
    SocialInteraction,
)


class SocialDataProvider(ABC):
    """
    Abstract interface for any social intelligence and content provider.
    Decouples underlying capability layers (Agent Reach, Apify, Native APIs, CLIs)
    from business and normalization logic.
    """

    platform_name: str
    provider_name: str

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is configured, authenticated, and ready to serve requests."""
        pass

    @abstractmethod
    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        """Search recent public content (posts, reels, videos, threads, repos) matching a query/topic."""
        pass

    @abstractmethod
    async def get_content(
        self, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Fetch full details of a specific piece of public content by URL or platform ID."""
        pass

    @abstractmethod
    async def get_comments(
        self, content_url_or_id: str, limit: int = 20
    ) -> List[SocialInteraction]:
        """Fetch public comments and interactions for a piece of content."""
        pass

    @abstractmethod
    async def get_profile(
        self, identifier: str
    ) -> Optional[SocialAuthor]:
        """Fetch publicly available author profile details."""
        pass

    def get_status(self) -> Dict[str, Any]:
        """Return provider health status and metadata."""
        return {
            "platform": self.platform_name,
            "provider": self.provider_name,
            "available": self.is_available(),
        }
