"""Reddit collector: rdt-cli (cookie auth from REDDIT_SESSION)."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.collection.cli import CliError, find_binary, run_cli
from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.models import CommentRow, PostCandidate, QueryPlan

logger = logging.getLogger("mcp_server.collection.reddit")

SITE = "https://www.reddit.com"
REMOVED = {"[deleted]", "[removed]"}
BOT_AUTHORS = {"automoderator"}  # moderation bot, not a person
AUTH_CODES = {"forbidden", "not_authenticated", "unauthorized", "auth_required", "login_required"}


def credential_path() -> Path:
    return Path.home() / ".config" / "rdt-cli" / "credential.json"


def ensure_credential(session: Optional[str] = None) -> bool:
    """Write rdt-cli's credential file from REDDIT_SESSION (rdt-cli has no env-var login).

    Returns True if a credential file is present afterwards. A credential file that was
    saved by the user (not by us) is left untouched when REDDIT_SESSION is not set.
    """
    session = session if session is not None else os.getenv("REDDIT_SESSION")
    path = credential_path()
    if not session:
        return path.exists()
    try:
        if path.exists():
            current = json.loads(path.read_text())
            if (current.get("cookies") or {}).get("reddit_session") == session:
                return True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "cookies": {"reddit_session": session},
                    "source": "env:REDDIT_SESSION",
                    "username": None,
                    "modhash": None,
                    "saved_at": time.time(),
                    "last_verified_at": None,
                }
            )
        )
        os.chmod(path, 0o600)
        return True
    except (OSError, ValueError) as exc:
        logger.warning("Could not write rdt-cli credential file: %s", type(exc).__name__)
        return path.exists()


def _parse(out: str) -> Dict[str, Any]:
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise CliError(f"rdt returned non-JSON output: {out[:120]!r}") from exc
    if not isinstance(data, dict):
        raise CliError("rdt returned unexpected JSON")
    if not data.get("ok", True):
        err = data.get("error") or {}
        code = str(err.get("code") or "").lower()
        msg = f"rdt error {code or 'unknown'}: {err.get('message', '')}"[:300]
        if code in AUTH_CODES:
            raise CollectorFatalError(msg + " (is REDDIT_SESSION valid / expired?)")
        raise CliError(msg)
    return data


class RedditCollector(PlatformCollector):
    platform = "reddit"
    batch_size = 3
    concurrency = 2

    SEARCH_KEYWORDS = 3
    SEARCH_SUBREDDITS = 3
    SEARCH_LIMIT = 50

    def __init__(self, binary: Optional[str] = None):
        self._binary = binary

    @property
    def binary(self) -> Optional[str]:
        return self._binary or find_binary("rdt")

    def is_available(self) -> bool:
        return self.binary is not None and (bool(os.getenv("REDDIT_SESSION")) or credential_path().exists())

    def unavailable_reason(self) -> str:
        if self.binary is None:
            return "rdt-cli is not installed (pip install rdt-cli)"
        return "REDDIT_SESSION is not set (the reddit_session cookie value)"

    # ---- discovery -----------------------------------------------------------------
    async def _search(self, args: List[str]) -> List[Dict[str, Any]]:
        try:
            _, out, _ = await run_cli([self.binary or "rdt", "search", *args, "--json"], timeout=60.0, allow_nonzero=True)
            data = _parse(out)
        except CliError as exc:
            logger.warning("Reddit search failed: %s", exc)
            return []
        children = ((data.get("data") or {}).get("data") or {}).get("children") or []
        return [c.get("data") or {} for c in children if c.get("kind") == "t3"]

    @staticmethod
    def _candidate(d: Dict[str, Any]) -> Optional[PostCandidate]:
        pid = d.get("id")
        if not pid or not d.get("num_comments"):
            return None
        created = d.get("created_utc")
        published = None
        if created:
            import datetime

            published = datetime.datetime.fromtimestamp(float(created), datetime.timezone.utc).isoformat()
        return PostCandidate(
            platform="reddit",
            post_id=pid,
            url=SITE + (d.get("permalink") or f"/comments/{pid}/"),
            title=d.get("title") or "",
            text=(d.get("selftext") or "")[:1500],
            author_username=d.get("author"),
            author_id=d.get("author_fullname"),
            comment_count=int(d.get("num_comments") or 0),
            like_count=d.get("score"),
            published_at=published,
            extra={"subreddit": d.get("subreddit")},
        )

    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        if not ensure_credential():
            raise CollectorFatalError("REDDIT_SESSION is not set")
        n = str(max(10, min(100, self.SEARCH_LIMIT)))
        keywords = plan.keywords[: self.SEARCH_KEYWORDS] or [plan.topic]
        jobs = [[kw, "-n", n, "--sort", "relevance", "--time", "year"] for kw in keywords]
        jobs += [
            [keywords[0], "-r", sub, "-n", "25", "--sort", "top", "--time", "month"]
            for sub in plan.subreddits[: self.SEARCH_SUBREDDITS]
        ]
        sem = asyncio.Semaphore(3)

        async def _run(a: List[str]) -> List[Dict[str, Any]]:
            async with sem:
                return await self._search(a)

        batches = await asyncio.gather(*[_run(a) for a in jobs])
        found: Dict[str, PostCandidate] = {}
        for batch in batches:
            for d in batch:
                cand = self._candidate(d)
                if cand and cand.post_id not in found:
                    found[cand.post_id] = cand
        return list(found.values())

    # ---- comments ------------------------------------------------------------------
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        if not ensure_credential():
            raise CollectorFatalError("REDDIT_SESSION is not set")
        # NOTE: no --expand-more: rdt-cli builds an over-long morechildren URL on big threads (HTTP 414).
        _, out, _ = await run_cli(
            [self.binary or "rdt", "read", post.post_id, "-n", str(max(1, int(max_comments))), "--sort", "top", "--json"],
            timeout=90.0,
            allow_nonzero=True,
        )
        data = _parse(out).get("data")
        if not isinstance(data, list) or len(data) < 2:
            return []
        listing = (data[1].get("data") or {}).get("children") or []
        rows: List[CommentRow] = []
        self._walk(listing, post.url, rows)
        return rows

    @classmethod
    def _walk(cls, children: List[Dict[str, Any]], post_url: str, rows: List[CommentRow]) -> None:
        for child in children:
            if child.get("kind") != "t1":
                continue  # "more" stubs
            d = child.get("data") or {}
            author = (d.get("author") or "").strip()
            body = d.get("body") or ""
            if author and author.lower() not in REMOVED and author.lower() not in BOT_AUTHORS \
                    and body.strip() not in REMOVED and not d.get("is_submitter"):
                created = d.get("created_utc")
                iso = None
                if created:
                    import datetime

                    iso = datetime.datetime.fromtimestamp(float(created), datetime.timezone.utc).isoformat()
                rows.append(
                    CommentRow(
                        platform="reddit",
                        username=author,
                        user_id=d.get("author_fullname"),
                        comment=body,
                        likes=int(d.get("score") or 0),
                        created_at=iso,
                        post_url=post_url,
                    )
                )
            replies = d.get("replies")
            if isinstance(replies, dict):
                cls._walk((replies.get("data") or {}).get("children") or [], post_url, rows)
