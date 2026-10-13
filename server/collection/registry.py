"""Factory for platform collectors: one provider chain per platform, cheapest provider first."""

from typing import Callable, Dict, List, Optional

from server.collection.collectors.base import PlatformCollector
from server.collection.collectors.chain import ChainedCollector
from server.collection.models import SUPPORTED_PLATFORMS


def _chain_spec() -> Dict[str, List[Callable[[], PlatformCollector]]]:
    """Ordered backends per platform: free tools, then cheap REST APIs, then batch actors.

    Capabilities are per backend (TrueScrape/Instagram can only read comments, Apify can do both),
    so the same list serves both discovery and comment fetching.
    """
    from server.collection.collectors.instagram import InstagramCollector
    from server.collection.collectors.reddit import RedditCollector
    from server.collection.collectors.serp import SerpDiscoveryBackend
    from server.collection.collectors.socialcrawl import SocialCrawlBackend
    from server.collection.collectors.truescrape import TrueScrapeBackend
    from server.collection.collectors.x import XCollector
    from server.collection.collectors.youtube import YouTubeCollector

    return {
        "youtube": [YouTubeCollector],
        "reddit": [RedditCollector, lambda: TrueScrapeBackend("reddit"), lambda: SocialCrawlBackend("reddit")],
        # twitter-cli reads replies for free; its search is broken (Oct 2026), so Google (SERP) finds the tweets
        "x": [XCollector, lambda: SerpDiscoveryBackend("x"), lambda: SocialCrawlBackend("x")],
        # SERP finds posts cheaply, TrueScrape reads their comments, Apify is the pricey fallback for both
        "instagram": [
            lambda: SerpDiscoveryBackend("instagram"),
            lambda: TrueScrapeBackend("instagram"),
            InstagramCollector,
            lambda: SocialCrawlBackend("instagram"),
        ],
        # comments still need SocialCrawl; SERP only adds a second way to find posts
        "linkedin": [lambda: SerpDiscoveryBackend("linkedin"), lambda: SocialCrawlBackend("linkedin")],
    }


def normalize_platforms(platforms: Optional[List[str]]) -> List[str]:
    aliases = {"twitter": "x", "yt": "youtube", "ig": "instagram", "li": "linkedin"}
    if not platforms:
        return list(SUPPORTED_PLATFORMS)
    out: List[str] = []
    for p in platforms:
        key = aliases.get(p.strip().lower(), p.strip().lower())
        if key in SUPPORTED_PLATFORMS and key not in out:
            out.append(key)
    return out


def get_collector(platform: str) -> ChainedCollector:
    spec = _chain_spec()
    if platform not in spec:
        raise ValueError(f"Unsupported or not yet implemented platform: {platform}")
    return ChainedCollector(platform, [make() for make in spec[platform]])
