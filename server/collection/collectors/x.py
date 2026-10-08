"""X / Twitter collector: twitter-cli (cookie auth via TWITTER_AUTH_TOKEN + TWITTER_CT0).

`twitter search <q> --json` finds tweets; `twitter tweet <id> --json` returns the tweet followed by
its replies. The replies are the "comments" we collect. Credentials reach the CLI only through the
process environment.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from server.collection.cli import CliError, find_binary, run_cli
from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.models import CommentRow, PostCandidate, QueryPlan

logger = logging.getLogger("mcp_server.collection.x")

AUTH_CODES = {"not_authenticated", "unauthorized", "forbidden", "auth_required", "authentication_failed"}
AUTH_HINT = " (X rejected TWITTER_AUTH_TOKEN / TWITTER_CT0 - the cookies are probably expired; copy fresh ones from x.com)"


def _parse(out: str) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise CliError(f"twitter returned non-JSON output: {out[:120]!r}") from exc
    if isinstance(payload, dict) and payload.get("ok") is False:
        err = payload.get("error") or {}
        code = str(err.get("code") or "").lower()
        msg = f"twitter error {code or 'unknown'}: {err.get('message', '')}"[:300]
        if code in AUTH_CODES:
            raise CollectorFatalError(msg + AUTH_HINT)
        raise CliError(msg)
    data = payload.get("data") if isinstance(payload, dict) else payload
    return [t for t in (data or []) if isinstance(t, dict)]


def tweet_url(tweet: Dict[str, Any]) -> str:
    screen = (tweet.get("author") or {}).get("screenName") or "i"
    return f"https://x.com/{screen}/status/{tweet.get('id')}"


class XCollector(PlatformCollector):
    platform = "x"
    batch_size = 1  # twitter-cli spaces its own requests; stay sequential to avoid rate limits
    concurrency = 1

    SEARCH_QUERIES = 3
    SEARCH_HASHTAGS = 2
    SEARCH_COUNT = 40

    def __init__(self, binary: Optional[str] = None):
        self._binary = binary

    @property
    def binary(self) -> Optional[str]:
        return self._binary or find_binary("twitter") or find_binary("twitter-cli")

    def is_available(self) -> bool:
        return self.binary is not None and bool(os.getenv("TWITTER_AUTH_TOKEN")) and bool(os.getenv("TWITTER_CT0"))

    def unavailable_reason(self) -> str:
        if self.binary is None:
            return "twitter-cli is not installed (pip install twitter-cli)"
        return "TWITTER_AUTH_TOKEN and TWITTER_CT0 must both be set"

    # ---- discovery -----------------------------------------------------------------
    async def _search(self, query: str, tab: str, count: int) -> List[Dict[str, Any]]:
        try:
            _, out, _ = await run_cli(
                [self.binary or "twitter", "search", query, "-t", tab, "-n", str(count),
                 "--exclude", "retweets", "--json"],
                timeout=60.0 + count * 2,
                allow_nonzero=True,
            )
            return _parse(out)
        except CliError as exc:
            logger.warning("X search failed: %s", exc)
            return []

    @staticmethod
    def _candidate(t: Dict[str, Any]) -> Optional[PostCandidate]:
        tid = t.get("id")
        metrics = t.get("metrics") or {}
        replies = int(metrics.get("replies") or 0)
        if not tid or replies <= 0:
            return None
        author = t.get("author") or {}
        text = t.get("text") or ""
        return PostCandidate(
            platform="x",
            post_id=str(tid),
            url=tweet_url(t),
            title=text[:200],
            text=text,
            author_username=author.get("screenName"),
            author_id=str(author["id"]) if author.get("id") else None,
            comment_count=replies,
            like_count=int(metrics.get("likes") or 0),
            view_count=int(metrics.get("views") or 0) or None,
            published_at=t.get("createdAtISO"),
        )

    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        queries = [(kw, "top") for kw in plan.keywords[: self.SEARCH_QUERIES]] or [(plan.topic, "top")]
        queries += [(f"#{h}", "top") for h in plan.hashtags[: self.SEARCH_HASHTAGS]]
        queries.append((queries[0][0], "latest"))
        count = max(10, min(100, self.SEARCH_COUNT))

        found: Dict[str, PostCandidate] = {}
        # sequential: each search is a handful of API calls and X rate-limits aggressively
        for q, tab in queries:
            for t in await self._search(q, tab, count):
                cand = self._candidate(t)
                if cand and cand.post_id not in found:
                    found[cand.post_id] = cand
        return list(found.values())

    # ---- comments ------------------------------------------------------------------
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        n = max(1, int(max_comments))
        _, out, _ = await run_cli(
            [self.binary or "twitter", "tweet", post.post_id, "-n", str(n + 1), "--json"],
            timeout=90.0 + n * 2,
            allow_nonzero=True,
        )
        tweets = _parse(out)
        rows: List[CommentRow] = []
        for t in tweets:
            if str(t.get("id")) == post.post_id:  # the focal tweet itself comes first
                continue
            author = t.get("author") or {}
            rows.append(
                CommentRow(
                    platform="x",
                    username=author.get("screenName") or "",
                    user_id=str(author["id"]) if author.get("id") else None,
                    comment=t.get("text") or "",
                    likes=int((t.get("metrics") or {}).get("likes") or 0),
                    created_at=t.get("createdAtISO"),
                    post_url=post.url,
                )
            )
        return rows
