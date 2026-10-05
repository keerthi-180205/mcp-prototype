"""YouTube social data provider implementation using Agent Reach (yt-dlp capability backend)."""

import datetime
import logging
import re
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger("mcp_server.providers.social.youtube")


class YouTubeSocialProvider(SocialDataProvider):
    """
    YouTube data provider utilizing the Agent Reach capability layer (backed by yt-dlp).
    Acquires public video metadata, titles, transcripts, and channel info.
    """

    platform_name = "youtube"
    provider_name = "agent-reach"

    def __init__(self, adapter: Optional[AgentReachAdapter] = None):
        self.adapter = adapter or AgentReachAdapter()

    def is_available(self) -> bool:
        """Available if agent-reach is installed and yt-dlp tool is enabled."""
        return self.adapter.is_installed()

    def _extract_video_id(self, url_or_id: str) -> str:
        """Extract 11-char YouTube video ID from URL or return string directly."""
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url_or_id)
        if match:
            return match.group(1)
        return url_or_id.strip()

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        """Search YouTube for videos matching a query via Agent Reach."""
        if not self.is_available():
            logger.warning("YouTubeSocialProvider skipped: agent-reach not installed")
            return []

        # yt-dlp search query via agent-reach youtube.info "ytsearch{limit}:{query}"
        search_target = f"ytsearch{limit}:{query}"
        data = await self.adapter.execute_command(
            "youtube.info", search_target, limit=limit, timeout=30.0
        )

        records: List[NormalizedSocialRecord] = []
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"

        if not data:
            return []

        # Handle multiple items or single item payload from yt-dlp
        entries = data.get("entries", [data]) if isinstance(data, dict) else []
        for item in entries:
            if not isinstance(item, dict):
                continue

            vid_id = item.get("id") or item.get("display_id")
            if not vid_id:
                continue

            webpage_url = item.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"
            title = item.get("title", "")
            description = item.get("description", "")
            uploader = item.get("uploader") or item.get("channel")
            channel_id = item.get("channel_id")
            channel_url = item.get("channel_url") or (f"https://www.youtube.com/channel/{channel_id}" if channel_id else None)
            upload_date = item.get("upload_date")  # YYYYMMDD
            published_at = None
            if upload_date and len(upload_date) == 8:
                published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00Z"

            tags = item.get("tags") or []
            if not tags and item.get("categories"):
                tags = item.get("categories")

            record = NormalizedSocialRecord(
                record_id=f"youtube:{vid_id}",
                platform="youtube",
                content_type="video",
                source_url=webpage_url,
                content_id=vid_id,
                published_at=published_at,
                author=SocialAuthor(
                    username=uploader,
                    user_id=channel_id,
                    display_name=uploader,
                    profile_url=channel_url,
                ),
                content=SocialContent(
                    title=title,
                    text=description[:500] if description else title,
                    caption=description[:250] if description else None,
                    tags=tags[:10],
                ),
                engagement=SocialEngagement(
                    likes=item.get("like_count"),
                    views=item.get("view_count"),
                    comments=item.get("comment_count"),
                ),
                interactions=[],
                metadata=ProvenanceMetadata(
                    source_platform="youtube",
                    source_provider="agent-reach",
                    backend_tool="yt-dlp",
                    fetched_at=now_iso,
                    source_url=webpage_url,
                ),
            )
            records.append(record)

        return records

    async def get_content(
        self, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Retrieve video details and transcript."""
        if not self.is_available():
            return None

        video_id = self._extract_video_id(content_url_or_id)
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        # Get metadata
        info_data = await self.adapter.execute_command("youtube.info", video_url, timeout=20.0)
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"

        title = "YouTube Video"
        text = ""
        author = SocialAuthor()
        published_at = None
        engagement = SocialEngagement()

        if info_data and isinstance(info_data, dict):
            title = info_data.get("title", title)
            text = info_data.get("description", "")
            author = SocialAuthor(
                username=info_data.get("uploader") or info_data.get("channel"),
                user_id=info_data.get("channel_id"),
                display_name=info_data.get("uploader"),
                profile_url=info_data.get("channel_url"),
            )
            upload_date = info_data.get("upload_date")
            if upload_date and len(upload_date) == 8:
                published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00Z"
            engagement = SocialEngagement(
                likes=info_data.get("like_count"),
                views=info_data.get("view_count"),
                comments=info_data.get("comment_count"),
            )

        # Optional transcript acquisition
        transcript_data = await self.adapter.execute_command(
            "youtube.transcript", video_url, timeout=20.0
        )
        if transcript_data:
            if isinstance(transcript_data, dict) and "raw_text" in transcript_data:
                transcript_text = transcript_data["raw_text"]
            else:
                transcript_text = str(transcript_data)
            if transcript_text:
                text = f"{text}\n\n[Transcript excerpt]:\n{transcript_text[:1000]}"

        return NormalizedSocialRecord(
            record_id=f"youtube:{video_id}",
            platform="youtube",
            content_type="video",
            source_url=video_url,
            content_id=video_id,
            published_at=published_at,
            author=author,
            content=SocialContent(
                title=title,
                text=text,
                caption=title,
            ),
            engagement=engagement,
            interactions=[],
            metadata=ProvenanceMetadata(
                source_platform="youtube",
                source_provider="agent-reach",
                backend_tool="yt-dlp",
                fetched_at=now_iso,
                source_url=video_url,
            ),
        )

    async def get_comments(
        self, content_url_or_id: str, limit: int = 20
    ) -> List[SocialInteraction]:
        """Fetch comments if supported by backend."""
        # Standard yt-dlp does not extract comment threads by default without additional flags
        return []

    async def get_profile(
        self, identifier: str
    ) -> Optional[SocialAuthor]:
        """Return public YouTube channel info."""
        clean_handle = identifier.replace("@", "").strip()
        return SocialAuthor(
            username=clean_handle,
            profile_url=f"https://www.youtube.com/@{clean_handle}",
        )
