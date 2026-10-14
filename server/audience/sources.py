"""Where the posts of MMTF's own accounts come from, and proof that a post really belongs to the account.

Instagram: a profile grid can also show collab / tagged posts owned by someone else, so every post is kept
only if its reported owner is the account; a post whose owner is unknown is dropped, never assumed.
YouTube: a channel's /videos page lists only that channel's uploads; a pasted video URL must appear in it.
"""

import datetime
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from server.collection.cli import CliError, find_binary, run_cli

WATCH_URL = "https://www.youtube.com/watch?v="


class SourceError(Exception):
    """The platform cannot be read right now (not configured, no credits, not installed)."""


@dataclass
class OwnPost:
    platform: str
    account: str
    url: str
    post_id: str
    caption: str = ""
    comment_count: Optional[int] = None
    published_at: Optional[str] = None


def clean_instagram_url(url: str) -> Optional[str]:
    """https://www.instagram.com/p/<code>/ without tracking parameters, or None if it is not a post / reel URL."""
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if not (host == "instagram.com" or host.endswith(".instagram.com")):
        return None
    m = re.match(r"^/(?:[A-Za-z0-9._]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)/?", parts.path)
    if not m:
        return None
    kind = "reel" if m.group(1) in ("reel", "reels") else m.group(1)
    return f"https://www.instagram.com/{kind}/{m.group(2)}/"


class InstagramSource:
    platform = "instagram"

    def __init__(self, backend: Any = None):
        self._backend = backend

    @property
    def backend(self) -> Any:
        if self._backend is None:
            from server.collection.collectors.truescrape import TrueScrapeBackend
            self._backend = TrueScrapeBackend("instagram")
        return self._backend

    @property
    def credits_used(self) -> float:
        return float(getattr(self.backend, "credits_used", 0.0) or 0.0)

    def check_ready(self) -> None:
        if not self.backend.is_available():
            raise SourceError(self.backend.unavailable_reason())

    @staticmethod
    def _own(account: str, facts: Dict[str, Any]) -> OwnPost:
        return OwnPost("instagram", account, facts["url"], facts["post_id"], facts.get("caption", ""),
                       facts.get("comment_count"), facts.get("published_at"))

    async def list_posts(self, account: str, max_posts: int) -> Tuple[List[OwnPost], List[str]]:
        grid = await self.backend.instagram_user_posts(account, max_posts + 6)   # a few extra: collabs are dropped below
        own: List[OwnPost] = []
        others = unknown = 0
        for facts in grid:
            owner = (facts.get("author_handle") or "").lstrip("@").lower()
            if not owner:
                unknown += 1
            elif owner != account:
                others += 1
            else:
                own.append(self._own(account, facts))
        notes = []
        if others:
            notes.append(f"skipped {others} collab / tagged post(s) owned by another account")
        if unknown:
            notes.append(f"skipped {unknown} post(s) whose owner could not be confirmed")
        return own[:max_posts], notes

    async def check_posts(self, urls: Sequence[str], account: str) -> Tuple[List[OwnPost], List[str]]:
        own: List[OwnPost] = []
        notes: List[str] = []
        for raw in urls:
            url = clean_instagram_url(raw)
            if not url:
                notes.append(f"not an Instagram post / reel URL: {raw[:80]}")
                continue
            facts = await self.backend.instagram_post(url)
            owner = ((facts or {}).get("author_handle") or "").lstrip("@").lower()
            if not facts or not owner:
                notes.append(f"could not confirm who owns {url}, so it was not collected")
            elif owner != account:
                notes.append(f"{url} belongs to @{owner}, not @{account}: not collected")
            else:
                own.append(self._own(account, {**facts, "url": url}))
        return own, notes


def _iso_from_upload_date(value: Optional[str]) -> Optional[str]:
    if value and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}T00:00:00+00:00"
    return None


class YouTubeSource:
    platform = "youtube"
    LOOKUP_LIMIT = 300      # how far back a pasted video URL is looked for in the channel's uploads

    def __init__(self, binary: Optional[str] = None, runner: Any = None):
        self._binary = binary
        self._run = runner or run_cli
        self.credits_used = 0.0   # yt-dlp is free

    @property
    def binary(self) -> Optional[str]:
        return self._binary or find_binary("yt-dlp")

    def check_ready(self) -> None:
        if not self.binary:
            raise SourceError("yt-dlp is not installed (pip install yt-dlp)")

    async def _uploads(self, account: str, limit: int) -> List[Dict[str, Any]]:
        try:
            _, out, _ = await self._run(
                [self.binary or "yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", "--playlist-end", str(limit),
                 f"https://www.youtube.com/@{account}/videos"], timeout=120.0)
        except CliError as exc:
            raise SourceError(f"could not list @{account}'s videos: {str(exc)[:160]}") from exc
        items = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return [i for i in items if i.get("id")]

    @staticmethod
    def _own(account: str, item: Dict[str, Any]) -> OwnPost:
        published = None
        if item.get("timestamp"):
            try:
                published = datetime.datetime.fromtimestamp(float(item["timestamp"]), datetime.timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                published = None
        return OwnPost("youtube", account, WATCH_URL + item["id"], item["id"], item.get("title") or "",
                       item.get("comment_count"), published or _iso_from_upload_date(item.get("upload_date")))

    async def list_posts(self, account: str, max_posts: int) -> Tuple[List[OwnPost], List[str]]:
        return [self._own(account, i) for i in (await self._uploads(account, max_posts))[:max_posts]], []

    async def check_posts(self, urls: Sequence[str], account: str) -> Tuple[List[OwnPost], List[str]]:
        uploads = {i["id"]: i for i in await self._uploads(account, self.LOOKUP_LIMIT)}
        own: List[OwnPost] = []
        notes: List[str] = []
        for raw in urls:
            m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", raw or "")
            if m and m.group(1) in uploads:
                own.append(self._own(account, uploads[m.group(1)]))
            else:
                notes.append(f"{(raw or '')[:80]} is not among the last {self.LOOKUP_LIMIT} uploads of @{account}: not collected")
        return own, notes


def get_source(platform: str) -> Any:
    sources = {"instagram": InstagramSource, "youtube": YouTubeSource}
    if platform not in sources:
        raise SourceError(f"own-post collection is not available for {platform} yet (supported: {', '.join(sources)})")
    return sources[platform]()
