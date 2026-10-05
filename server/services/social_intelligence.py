"""Orchestrator service for Universal Social Intelligence and Outreach Data Platform."""

import logging
from typing import Any, Dict, List, Optional

from server.models import (
    NormalizedSocialRecord,
    SocialAuthor,
    SocialIntelligenceReport,
    SocialInteraction,
)
from server.providers.social.registry import SocialProviderRegistry, get_social_registry
from server.services.filtering import (
    filter_by_recency,
    filter_by_relevance,
    generate_social_report,
)
from server.storage.sqlite import get_social_records, save_social_records

logger = logging.getLogger("mcp_server.services.social_intelligence")


class SocialIntelligenceService:
    """
    Coordinates multi-platform discovery, provider routing,
    normalization, recency & relevance filtering, deduplication, and persistence.
    """

    def __init__(self, registry: Optional[SocialProviderRegistry] = None):
        self.registry = registry or get_social_registry()

    async def search_content(
        self,
        platform: str,
        topic: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        months_back: Optional[int] = 3,
        max_results: int = 10,
    ) -> List[NormalizedSocialRecord]:
        """Search and normalize content for a specific platform with recency filtering."""
        provider = self.registry.get_provider(platform)
        if not provider:
            logger.error("No provider registered for platform: %s", platform)
            return []

        records = await provider.search_content(query=topic, limit=max_results)

        # Apply recency filter
        if date_from or date_to or months_back:
            records = filter_by_recency(
                records, months_back=months_back, date_from=date_from, date_to=date_to
            )

        # Score relevance
        records = await filter_by_relevance(records, topic=topic, min_score=0.1)

        return records[:max_results]

    async def get_content(
        self, platform: str, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Fetch a specific post, video, or discussion."""
        provider = self.registry.get_provider(platform)
        if not provider:
            return None
        return await provider.get_content(content_url_or_id)

    async def get_comments(
        self, platform: str, content_url_or_id: str, max_comments: int = 20
    ) -> List[SocialInteraction]:
        """Fetch comments for a given piece of content."""
        provider = self.registry.get_provider(platform)
        if not provider:
            return []
        return await provider.get_comments(content_url_or_id, limit=max_comments)

    async def get_profile(
        self, platform: str, identifier: str
    ) -> Optional[SocialAuthor]:
        """Fetch public profile metadata."""
        provider = self.registry.get_provider(platform)
        if not provider:
            return None
        return await provider.get_profile(identifier)

    async def search_multi_platform(
        self,
        topic: str,
        platforms: Optional[List[str]] = None,
        months_back: int = 3,
        max_results_per_platform: int = 10,
        min_relevance: float = 0.2,
        auto_store: bool = True,
    ) -> List[NormalizedSocialRecord]:
        """
        Execute concurrent multi-platform discovery, normalize records,
        apply recency and relevance filters, deduplicate, and store results.
        """
        raw_records = await self.registry.search_multi_platform(
            topic=topic,
            platforms=platforms,
            max_per_platform=max_results_per_platform,
        )

        # Recency filtering
        recent_records = filter_by_recency(raw_records, months_back=months_back)

        # Relevance filtering
        relevant_records = await filter_by_relevance(
            recent_records, topic=topic, min_score=min_relevance
        )

        # Auto persistence and deduplication
        if auto_store and relevant_records:
            save_social_records(relevant_records)

        return relevant_records

    def store_records(self, records: List[NormalizedSocialRecord]) -> Dict[str, int]:
        """Persist records to SQLite with deduplication."""
        return save_social_records(records)

    def query_stored(
        self, platform: Optional[str] = None, topic: Optional[str] = None, limit: int = 50
    ) -> List[NormalizedSocialRecord]:
        """Query previously stored records."""
        return get_social_records(platform=platform, topic=topic, limit=limit)

    def generate_report(
        self, records: List[NormalizedSocialRecord], topic: str
    ) -> SocialIntelligenceReport:
        """Synthesize records into a structured executive report."""
        return generate_social_report(records, topic=topic)


_service_instance: Optional[SocialIntelligenceService] = None


def get_social_intelligence_service() -> SocialIntelligenceService:
    """Singleton accessor for SocialIntelligenceService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = SocialIntelligenceService()
    return _service_instance
