"""Central registry and router for multi-platform social data providers."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from server.models import NormalizedSocialRecord
from server.providers.social.agent_reach_adapter import AgentReachAdapter
from server.providers.social.base import SocialDataProvider
from server.providers.social.github_social import GitHubSocialProvider
from server.providers.social.instagram import InstagramSocialProvider
from server.providers.social.stubs import (
    FacebookSocialProvider,
    LinkedInSocialProvider,
    XTwitterSocialProvider,
)
from server.providers.social.reddit_opencli import RedditOpenCLIProvider
from server.providers.social.web_rss import WebRSSSocialProvider
from server.providers.social.youtube import YouTubeSocialProvider

logger = logging.getLogger("mcp_server.providers.social.registry")


class SocialProviderRegistry:
    """
    Central router managing social providers, capability layers,
    and multi-platform concurrent discovery with fallback handling.
    """

    def __init__(self):
        self._providers: Dict[str, List[SocialDataProvider]] = {}
        self.agent_reach = AgentReachAdapter()
        self._initialize_default_providers()

    def _initialize_default_providers(self) -> None:
        """Register default provider instances for supported platforms."""
        # Instagram: Primary Apify
        self.register_provider(InstagramSocialProvider())

        # YouTube: Primary Agent Reach (yt-dlp)
        self.register_provider(YouTubeSocialProvider(adapter=self.agent_reach))

        # GitHub: Primary GitHub API
        self.register_provider(GitHubSocialProvider())

        # Web & RSS: Primary Agent Reach & Jina Reader
        self.register_provider(WebRSSSocialProvider(adapter=self.agent_reach))

        # Stubs / Configurable:
        self.register_provider(RedditOpenCLIProvider())
        self.register_provider(XTwitterSocialProvider())
        self.register_provider(LinkedInSocialProvider())
        self.register_provider(FacebookSocialProvider())

    def register_provider(self, provider: SocialDataProvider, is_primary: bool = True) -> None:
        """Register a provider for a platform. If is_primary is True, it will be prioritized."""
        platform = provider.platform_name.lower()
        if platform not in self._providers:
            self._providers[platform] = []
        if is_primary:
            self._providers[platform].insert(0, provider)
        else:
            self._providers[platform].append(provider)
        logger.debug(
            "Registered provider '%s' for platform '%s' (primary=%s)",
            provider.provider_name,
            platform,
            is_primary,
        )

    def get_provider(self, platform: str) -> Optional[SocialDataProvider]:
        """
        Retrieve the highest-priority available provider for the given platform.
        Falls back to alternative providers if primary is unavailable.
        """
        candidates = self._providers.get(platform.lower(), [])
        for prov in candidates:
            if prov.is_available():
                return prov
        # If none report available, return the primary candidate anyway so callers receive descriptive errors
        return candidates[0] if candidates else None

    def list_supported_platforms(self) -> List[str]:
        """Return a list of all registered platform identifiers."""
        return list(self._providers.keys())

    async def get_system_health(self) -> Dict[str, Any]:
        """Check availability across all registered providers and capability backends."""
        platforms_status = {}
        for platform, prov_list in self._providers.items():
            platforms_status[platform] = [p.get_status() for p in prov_list]

        agent_reach_status = await self.agent_reach.get_doctor_status()

        return {
            "status": "healthy",
            "platforms": platforms_status,
            "capability_layers": {
                "agent_reach": agent_reach_status,
            },
        }

    async def search_multi_platform(
        self,
        topic: str,
        platforms: Optional[List[str]] = None,
        max_per_platform: int = 10,
        **kwargs: Any,
    ) -> List[NormalizedSocialRecord]:
        """
        Concurrently execute topic discovery across multiple platforms.
        Collects results into a unified list of NormalizedSocialRecord.
        """
        target_platforms = (
            [p.lower().strip() for p in platforms]
            if platforms
            else ["instagram", "youtube", "github"]
        )

        tasks = []
        platform_names = []

        for p_name in target_platforms:
            provider = self.get_provider(p_name)
            if provider and provider.is_available():
                platform_names.append(p_name)
                tasks.append(provider.search_content(query=topic, limit=max_per_platform, **kwargs))
            else:
                logger.info("Platform '%s' skipped (provider unavailable or unconfigured)", p_name)

        if not tasks:
            logger.warning("No available providers found for requested platforms: %s", target_platforms)
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        combined_records: List[NormalizedSocialRecord] = []
        for p_name, res in zip(platform_names, results):
            if isinstance(res, Exception):
                logger.error("Search on platform '%s' failed: %s", p_name, res)
            elif isinstance(res, list):
                logger.info("Retrieved %d records from platform '%s'", len(res), p_name)
                combined_records.extend(res)

        return combined_records


_registry_instance: Optional[SocialProviderRegistry] = None


def get_social_registry() -> SocialProviderRegistry:
    """Singleton accessor for SocialProviderRegistry."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = SocialProviderRegistry()
    return _registry_instance
