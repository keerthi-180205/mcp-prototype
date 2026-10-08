"""Factory for platform collectors."""

from typing import Dict, List, Optional

from server.collection.collectors.base import PlatformCollector
from server.collection.models import SUPPORTED_PLATFORMS


def _factories():
    from server.collection.collectors.youtube import YouTubeCollector

    table = {"youtube": YouTubeCollector}
    for name, module, cls in (
        ("instagram", "instagram", "InstagramCollector"),
        ("reddit", "reddit", "RedditCollector"),
        ("x", "x", "XCollector"),
    ):
        try:
            mod = __import__(f"server.collection.collectors.{module}", fromlist=[cls])
            table[name] = getattr(mod, cls)
        except ImportError:
            continue
    return table


def normalize_platforms(platforms: Optional[List[str]]) -> List[str]:
    aliases = {"twitter": "x", "yt": "youtube", "ig": "instagram"}
    if not platforms:
        return list(SUPPORTED_PLATFORMS)
    out: List[str] = []
    for p in platforms:
        key = aliases.get(p.strip().lower(), p.strip().lower())
        if key in SUPPORTED_PLATFORMS and key not in out:
            out.append(key)
    return out


def get_collector(platform: str) -> PlatformCollector:
    table: Dict[str, type] = _factories()
    if platform not in table:
        raise ValueError(f"Unsupported or not yet implemented platform: {platform}")
    return table[platform]()
