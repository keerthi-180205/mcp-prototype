"""Web and RSS social and blog discovery provider."""

import datetime
import hashlib
import logging
from typing import Any, Dict, List, Optional

import httpx

from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialInteraction,
)
from server.providers.social.agent_reach_adapter import AgentReachAdapter
from server.providers.social.base import SocialDataProvider

logger = logging.getLogger("mcp_server.providers.social.web_rss")


class WebRSSSocialProvider(SocialDataProvider):
    """
    Acquires public web articles, documentation, blogs, and RSS feeds
    using Agent Reach (rss.feed / Jina Reader) and HTTP readers.
    """

    platform_name = "web"
    provider_name = "agent-reach"

    def __init__(self, adapter: Optional[AgentReachAdapter] = None):
        self.adapter = adapter or AgentReachAdapter()

    def is_available(self) -> bool:
        """Available via Agent Reach or direct HTTP reader."""
        return True

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        """Search RSS feeds or web resources matching query."""
        # Check if query is an RSS feed URL
        if query.startswith("http://") or query.startswith("https://"):
            data = await self.adapter.execute_command("rss.feed", query, limit=limit)
            if data and isinstance(data, dict):
                entries = data.get("entries", [])
                records: List[NormalizedSocialRecord] = []
                now_iso = datetime.datetime.utcnow().isoformat() + "Z"
                for item in entries[:limit]:
                    link = item.get("link", query)
                    title = item.get("title", "Article")
                    summary = item.get("summary", "")
                    content_id = hashlib.md5(link.encode()).hexdigest()[:12]
                    records.append(
                        NormalizedSocialRecord(
                            record_id=f"rss:{content_id}",
                            platform="rss",
                            content_type="article",
                            source_url=link,
                            content_id=content_id,
                            published_at=item.get("published"),
                            author=SocialAuthor(username=item.get("author")),
                            content=SocialContent(title=title, text=summary, caption=title),
                            engagement=SocialEngagement(),
                            interactions=[],
                            metadata=ProvenanceMetadata(
                                source_platform="rss",
                                source_provider="agent-reach",
                                backend_tool="feedparser",
                                fetched_at=now_iso,
                                source_url=link,
                            ),
                        )
                    )
                return records

        return []

    async def get_content(
        self, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Fetch article content via Jina Reader (r.jina.ai/<url>) or Agent Reach."""
        url = content_url_or_id
        if not url.startswith("http"):
            return None

        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        content_id = hashlib.md5(url.encode()).hexdigest()[:12]

        jina_url = f"https://r.jina.ai/{url}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(jina_url, headers={"Accept": "text/markdown"})
                if resp.status_code == 200:
                    text = resp.text
                    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                    title = lines[0].replace("#", "").strip() if lines else "Web Article"

                    return NormalizedSocialRecord(
                        record_id=f"web:{content_id}",
                        platform="web",
                        content_type="article",
                        source_url=url,
                        content_id=content_id,
                        published_at=now_iso,
                        author=SocialAuthor(),
                        content=SocialContent(
                            title=title,
                            text=text[:2500],
                            caption=text[:200],
                        ),
                        engagement=SocialEngagement(),
                        interactions=[],
                        metadata=ProvenanceMetadata(
                            source_platform="web",
                            source_provider="jina_reader",
                            backend_tool="r.jina.ai",
                            fetched_at=now_iso,
                            source_url=url,
                        ),
                    )
        except Exception as e:
            logger.warning("Failed to fetch web content via Jina reader: %s", e)

        return None

    async def get_comments(
        self, content_url_or_id: str, limit: int = 20
    ) -> List[SocialInteraction]:
        return []

    async def get_profile(
        self, identifier: str
    ) -> Optional[SocialAuthor]:
        return SocialAuthor(profile_url=identifier)
