import asyncio
import datetime
import json
import logging
import re
import shutil
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
        """Available if yt-dlp or agent-reach is available on system."""
        return bool(shutil.which("yt-dlp") or self.adapter.is_installed())

    def _extract_video_id(self, url_or_id: str) -> str:
        """Extract 11-char YouTube video ID from URL or return string directly."""
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url_or_id)
        if match:
            return match.group(1)
        return url_or_id.strip()

    async def _run_yt_dlp(self, args: List[str], timeout: float = 30.0) -> Optional[str]:
        """Execute yt-dlp binary asynchronously with timeout."""
        try:
            yt_bin = shutil.which("yt-dlp") or "yt-dlp"
            proc = await asyncio.create_subprocess_exec(
                yt_bin,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode().strip()
        except Exception as exc:
            logger.warning("yt-dlp subprocess execution error: %s", exc)
            return None

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        """Search YouTube for videos matching a query via Agent Reach / yt-dlp."""
        if not self.is_available():
            logger.warning("YouTubeSocialProvider skipped: agent-reach / yt-dlp not available")
            return []

        clean_limit = max(1, min(limit, 50))
        raw_output = await self._run_yt_dlp([
            f"ytsearch{clean_limit}:{query}",
            "--dump-json",
            "--flat-playlist",
            "--no-playlist",
        ], timeout=25.0)

        entries: List[Dict[str, Any]] = []
        if raw_output:
            for line in raw_output.split("\n"):
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue

        if not entries:
            # Fallback to adapter
            search_target = f"ytsearch{clean_limit}:{query}"
            data = await self.adapter.execute_command(
                "youtube.info", search_target, limit=clean_limit, timeout=30.0
            )
            if isinstance(data, dict):
                entries = data.get("entries", [data])

        records: List[NormalizedSocialRecord] = []
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not entries:
            return []

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

        # Fetch metadata using yt-dlp directly or adapter fallback
        info_data = None
        raw_output = await self._run_yt_dlp(["--dump-json", "--no-playlist", video_url], timeout=25.0)
        if raw_output:
            try:
                info_data = json.loads(raw_output)
            except Exception:
                pass

        if not info_data:
            info_data = await self.adapter.execute_command("youtube.info", video_url, timeout=20.0)

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        title = "YouTube Video"
        text = ""
        author = SocialAuthor()
        published_at = None
        engagement = SocialEngagement()
        tags: List[str] = []

        if info_data and isinstance(info_data, dict):
            title = info_data.get("title", title)
            text = info_data.get("description", "")
            tags = (info_data.get("tags") or info_data.get("categories") or [])[:10]
            author = SocialAuthor(
                username=info_data.get("uploader_id") or info_data.get("uploader") or info_data.get("channel"),
                user_id=info_data.get("channel_id"),
                display_name=info_data.get("uploader") or info_data.get("channel"),
                profile_url=info_data.get("channel_url") or info_data.get("uploader_url"),
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
                text=text[:1000] if text else title,
                caption=title,
                tags=tags,
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
        """Fetch public comments for a YouTube video via yt-dlp."""
        video_id = self._extract_video_id(content_url_or_id)
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        safe_limit = max(1, min(limit, 100))

        raw_output = await self._run_yt_dlp([
            "--write-comments",
            "--extractor-args",
            f"youtube:max_comments={safe_limit}",
            "--dump-json",
            "--no-playlist",
            video_url,
        ], timeout=25.0)

        if not raw_output:
            return []

        interactions: List[SocialInteraction] = []
        try:
            data = json.loads(raw_output)
            comments = data.get("comments", [])
            for c in comments[:safe_limit]:
                cid = c.get("id") or str(c.get("timestamp") or "")
                c_author = (c.get("author") or "").strip()
                clean_user = c_author.lstrip("@") or "anonymous"
                c_author_id = c.get("author_id")
                c_author_url = c.get("author_url")
                c_text = c.get("text") or ""
                c_likes = c.get("like_count") or 0
                ts = c.get("timestamp")
                c_time = None
                if ts:
                    c_time = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()

                interactions.append(
                    SocialInteraction(
                        interaction_id=cid,
                        type="comment",
                        text=c_text,
                        author=SocialAuthor(
                            username=clean_user,
                            user_id=c_author_id,
                            display_name=c_author or clean_user,
                            profile_url=c_author_url,
                            is_verified=c.get("author_is_verified", False),
                        ),
                        created_at=c_time,
                        likes=c_likes,
                    )
                )
        except Exception as exc:
            logger.warning("Error parsing YouTube comments: %s", exc)

        return interactions

    async def get_profile(
        self, identifier: str
    ) -> Optional[SocialAuthor]:
        """Return public YouTube channel info."""
        clean_handle = identifier.replace("@", "").strip()
        channel_url = f"https://www.youtube.com/@{clean_handle}"
        display_name = clean_handle
        channel_id = None

        try:
            raw_channel = await self._run_yt_dlp(
                ["--dump-json", "--flat-playlist", "--playlist-items", "1", channel_url],
                timeout=10.0,
            )
            if raw_channel:
                for line in raw_channel.split("\n"):
                    if line.strip():
                        item = json.loads(line)
                        display_name = item.get("channel") or item.get("uploader") or clean_handle
                        channel_id = item.get("channel_id")
                        break
        except Exception:
            pass

        return SocialAuthor(
            username=clean_handle,
            user_id=channel_id,
            display_name=display_name,
            profile_url=channel_url,
        )
