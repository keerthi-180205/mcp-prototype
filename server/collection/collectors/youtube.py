"""YouTube collector: yt-dlp for search, metadata and comments (no login needed)."""

import asyncio
import datetime
import json
import logging
import math
import os
from typing import Any, Dict, List, Optional

from server.collection.cli import CliError, find_binary, run_cli
from server.collection.collectors.base import PlatformCollector
from server.collection.models import CommentRow, PostCandidate, QueryPlan
from server.collection.ranking import relevance_score

logger = logging.getLogger("mcp_server.collection.youtube")

WATCH_URL = "https://www.youtube.com/watch?v="


def _iso_from_ts(ts: Any) -> Optional[str]:
    try:
        return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _iso_from_upload_date(value: Optional[str]) -> Optional[str]:
    if value and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}T00:00:00+00:00"
    return None


def _parse_json_lines(text: str) -> List[Dict[str, Any]]:
    items = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


class YouTubeCollector(PlatformCollector):
    platform = "youtube"
    batch_size = 3
    concurrency = 3

    SEARCH_KEYWORDS = 3
    ENRICH_LIMIT = 16
    ENRICH_CONCURRENCY = 4

    def __init__(self, binary: Optional[str] = None, player_client: Optional[str] = None):
        self._binary = binary
        # Default web clients are bot-checked from datacenter IPs; mweb serves comments without login.
        self.player_client = player_client or os.getenv("YOUTUBE_PLAYER_CLIENT", "mweb")
        self.cookies_file = os.getenv("YOUTUBE_COOKIES_FILE")

    @property
    def binary(self) -> Optional[str]:
        return self._binary or find_binary("yt-dlp")

    def is_available(self) -> bool:
        return self.binary is not None

    def unavailable_reason(self) -> str:
        return "yt-dlp is not installed (pip install yt-dlp)"

    def _base_args(self, extractor_args: str = "") -> List[str]:
        args = [
            self.binary or "yt-dlp",
            "--skip-download",
            "--ignore-no-formats-error",
            "--no-playlist",
            "--no-warnings",
            "--extractor-args",
            f"youtube:player_client={self.player_client}{';' + extractor_args if extractor_args else ''}",
        ]
        if self.cookies_file:
            args += ["--cookies", self.cookies_file]
        return args

    # ---- discovery -----------------------------------------------------------------
    async def _search(self, query: str, n: int) -> List[Dict[str, Any]]:
        try:
            _, out, _ = await run_cli(
                [self.binary or "yt-dlp", f"ytsearch{n}:{query}", "--flat-playlist", "--dump-json", "--no-warnings"],
                timeout=60.0,
            )
        except CliError as exc:
            logger.warning("YouTube search failed for %r: %s", query, exc)
            return []
        return _parse_json_lines(out)

    async def _metadata(self, video_id: str) -> Optional[Dict[str, Any]]:
        try:
            _, out, _ = await run_cli(
                self._base_args() + ["--dump-json", WATCH_URL + video_id], timeout=60.0
            )
        except CliError as exc:
            logger.info("YouTube metadata failed for %s: %s", video_id, exc)
            return None
        items = _parse_json_lines(out)
        return items[0] if items else None

    @staticmethod
    def _candidate(item: Dict[str, Any]) -> Optional[PostCandidate]:
        vid = item.get("id")
        if not vid:
            return None
        published = _iso_from_ts(item.get("timestamp")) or _iso_from_upload_date(item.get("upload_date"))
        return PostCandidate(
            platform="youtube",
            post_id=vid,
            url=WATCH_URL + vid,
            title=item.get("title") or "",
            text=(item.get("description") or "")[:1000],
            author_username=item.get("uploader_id") or item.get("channel") or item.get("uploader"),
            author_id=item.get("channel_id"),
            comment_count=item.get("comment_count"),
            like_count=item.get("like_count"),
            view_count=item.get("view_count"),
            published_at=published,
            extra={"channel_name": item.get("channel") or item.get("uploader")},
        )

    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        queries = plan.keywords[: self.SEARCH_KEYWORDS] or [plan.topic]
        per_query = max(5, min(50, limit))
        results = await asyncio.gather(*[self._search(q, per_query) for q in queries])

        merged: Dict[str, PostCandidate] = {}
        for items in results:
            for item in items:
                cand = self._candidate(item)
                if cand and cand.post_id not in merged:
                    merged[cand.post_id] = cand

        # Flat search results carry no comment count / date: enrich the most promising ones
        # (topic relevance of the title x log views), not simply the most viewed.
        def _prescore(c: PostCandidate) -> float:
            return relevance_score(plan.topic, c.title) * math.log1p(c.view_count or 0)

        to_enrich = sorted(merged.values(), key=_prescore, reverse=True)[: self.ENRICH_LIMIT]
        sem = asyncio.Semaphore(self.ENRICH_CONCURRENCY)

        async def _enrich(c: PostCandidate) -> None:
            async with sem:
                meta = await self._metadata(c.post_id)
            full = self._candidate(meta) if meta else None
            if full:
                full.relevance = c.relevance
                merged[c.post_id] = full

        await asyncio.gather(*[_enrich(c) for c in to_enrich])
        ordered = sorted(merged.values(), key=_prescore, reverse=True)
        return ordered[: max(limit, self.ENRICH_LIMIT)]

    # ---- comments ------------------------------------------------------------------
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        n = max(1, int(max_comments))
        spec = f"max_comments={n},{n},{n},10;comment_sort=top"
        _, out, _ = await run_cli(
            self._base_args(spec) + ["--write-comments", "--dump-json", post.url],
            timeout=90.0 + n * 0.5,
        )
        items = _parse_json_lines(out)
        if not items:
            return []
        data = items[0]
        if not post.author_id and data.get("channel_id"):
            post.author_id = data["channel_id"]

        rows: List[CommentRow] = []
        for c in data.get("comments") or []:
            if c.get("author_is_uploader"):
                continue
            handle = (c.get("author") or "").strip().lstrip("@")
            rows.append(
                CommentRow(
                    platform="youtube",
                    username=handle,
                    user_id=c.get("author_id"),
                    comment=c.get("text") or "",
                    likes=int(c.get("like_count") or 0),
                    created_at=_iso_from_ts(c.get("timestamp")),
                    post_url=post.url,
                )
            )
        return rows
