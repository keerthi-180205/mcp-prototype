"""SQLite persistence for the audience of MMTF's own accounts: comments, their triage and the reply queue.

Personal data lives here (usernames + what they said), so the table is built to be emptied: handled rows
expire after a retention period, and one person's rows can be erased on request.
"""

import datetime
import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence

from server.audience.models import CARE_LABELS, STATUSES, AudienceComment
from server.storage.sqlite import get_connection

DEFAULT_RETENTION_DAYS = 90


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def init_tables(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audience_comments (
                    comment_key TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    account TEXT NOT NULL,
                    post_url TEXT NOT NULL,
                    comment_id TEXT,
                    parent_id TEXT,
                    username TEXT NOT NULL DEFAULT '',
                    user_id TEXT,
                    comment TEXT NOT NULL,
                    likes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    collected_at TEXT NOT NULL,
                    provider TEXT,
                    label TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    reasons_json TEXT NOT NULL DEFAULT '[]',
                    possible_minor INTEGER NOT NULL DEFAULT 0,
                    generic INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'new',
                    handled_by TEXT NOT NULL DEFAULT '',
                    handled_at TEXT,
                    handler_note TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_aud_queue ON audience_comments(status, priority DESC);
                CREATE INDEX IF NOT EXISTS idx_aud_post ON audience_comments(post_url);
                CREATE INDEX IF NOT EXISTS idx_aud_user ON audience_comments(platform, username);
                CREATE TABLE IF NOT EXISTS audience_posts (
                    post_url TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    account TEXT NOT NULL,
                    post_id TEXT,
                    caption TEXT NOT NULL DEFAULT '',
                    comment_count INTEGER,
                    published_at TEXT,
                    last_collected_at TEXT
                );
                """
            )
    finally:
        conn.close()


def _conn(db_path: Optional[str]) -> sqlite3.Connection:
    init_tables(db_path)
    return get_connection(db_path)


def _row(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    d["reasons"] = json.loads(d.pop("reasons_json") or "[]")
    d["possible_minor"] = bool(d["possible_minor"])
    d["generic"] = bool(d["generic"])
    return d


# ---- posts + comments -------------------------------------------------------------------------------------------
def upsert_post(post: Dict[str, Any], db_path: Optional[str] = None) -> None:
    conn = _conn(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO audience_posts (post_url, platform, account, post_id, caption, comment_count, published_at, last_collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(post_url) DO UPDATE SET caption=excluded.caption, "
                "comment_count=excluded.comment_count, last_collected_at=excluded.last_collected_at",
                (post["url"], post["platform"], post["account"], post.get("post_id"), post.get("caption", ""),
                 post.get("comment_count"), post.get("published_at"), now_iso()),
            )
    finally:
        conn.close()


def upsert_comments(rows: Iterable[AudienceComment], db_path: Optional[str] = None) -> Dict[str, int]:
    """Insert new comments with their triage; for known ones only refresh likes. A reviewer's decision
    (status, who, note) is never overwritten by a later collection."""
    new = updated = new_care = 0
    conn = _conn(db_path)
    try:
        with conn:
            for c in rows:
                key = c.key
                if conn.execute("SELECT 1 FROM audience_comments WHERE comment_key=?", (key,)).fetchone():
                    conn.execute("UPDATE audience_comments SET likes=?, collected_at=? WHERE comment_key=?", (c.likes, now_iso(), key))
                    updated += 1
                    continue
                t = c.triage
                conn.execute(
                    "INSERT INTO audience_comments (comment_key, platform, account, post_url, comment_id, parent_id, username, user_id, comment, "
                    "likes, created_at, collected_at, provider, label, priority, reasons_json, possible_minor, generic) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, c.platform, c.account, c.post_url, c.comment_id, c.parent_id, c.username, c.user_id, c.comment, c.likes,
                     c.created_at, now_iso(), c.provider, t.label, t.priority, json.dumps(t.reasons), int(t.possible_minor), int(t.generic)),
                )
                new += 1
                new_care += t.label in CARE_LABELS
    finally:
        conn.close()
    return {"new": new, "updated": updated, "new_care": new_care}


# ---- the care queue --------------------------------------------------------------------------------------------------
def list_queue(statuses: Sequence[str] = ("new",), labels: Optional[Sequence[str]] = None, limit: int = 50,
               platform: Optional[str] = None, account: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    labels = [l for l in (labels or CARE_LABELS) if l in CARE_LABELS]
    statuses = [s for s in statuses if s in STATUSES]
    if not labels or not statuses:
        return []
    sql = (f"SELECT * FROM audience_comments WHERE label IN ({','.join('?' * len(labels))}) AND status IN ({','.join('?' * len(statuses))})")
    args: List[Any] = [*labels, *statuses]
    for column, value in (("platform", platform), ("account", account)):
        if value:
            sql += f" AND {column}=?"
            args.append(value)
    sql += " ORDER BY priority DESC, COALESCE(created_at, collected_at) ASC LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    conn = _conn(db_path)
    try:
        return [_row(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def get_comment(key: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = _conn(db_path)
    try:
        r = conn.execute("SELECT * FROM audience_comments WHERE comment_key=?", (key,)).fetchone()
        return _row(r) if r else None
    finally:
        conn.close()


def resolve_key(prefix: str, db_path: Optional[str] = None) -> str:
    """Expand the start of a comment key (as printed by the CLI) to the full key, or raise ValueError."""
    prefix = (prefix or "").strip().lower()
    if len(prefix) < 6 or not all(ch in "0123456789abcdef" for ch in prefix):
        raise ValueError("give at least 6 characters of the key shown in the queue")
    conn = _conn(db_path)
    try:
        keys = [r["comment_key"] for r in conn.execute("SELECT comment_key FROM audience_comments WHERE comment_key LIKE ? LIMIT 3", (prefix + "%",))]
    finally:
        conn.close()
    if not keys:
        raise ValueError(f"no comment starts with {prefix}")
    if len(keys) > 1:
        raise ValueError(f"{prefix} matches more than one comment; type more of the key")
    return keys[0]


def set_status(key: str, status: str, handled_by: str = "", note: str = "", db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    conn = _conn(db_path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE audience_comments SET status=?, handled_by=?, handled_at=?, handler_note=? WHERE comment_key=?",
                (status, handled_by.strip(), None if status == "new" else now_iso(), note.strip(), key),
            )
        if not cur.rowcount:
            return None
    finally:
        conn.close()
    return get_comment(key, db_path)


def list_comments(platform: Optional[str] = None, account: Optional[str] = None, labels: Optional[Sequence[str]] = None,
                  post_urls: Optional[Sequence[str]] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    sql, args = "SELECT * FROM audience_comments WHERE 1=1", []
    for column, value in (("platform", platform), ("account", account)):
        if value:
            sql += f" AND {column}=?"
            args.append(value)
    if labels:
        sql += f" AND label IN ({','.join('?' * len(labels))})"
        args += list(labels)
    if post_urls:
        sql += f" AND post_url IN ({','.join('?' * len(post_urls))})"
        args += list(post_urls)
    sql += " ORDER BY post_url, COALESCE(created_at, collected_at)"
    conn = _conn(db_path)
    try:
        return [_row(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


# ---- keeping less ------------------------------------------------------------------------------------------------------
def purge(retention_days: int = DEFAULT_RETENTION_DAYS, db_path: Optional[str] = None) -> Dict[str, int]:
    """Delete what is no longer needed: handled care items, and ordinary comments, older than the retention period.
    A care item nobody has handled yet is never deleted: a person must see it first."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max(0, retention_days))).isoformat()
    care = ",".join(f"'{l}'" for l in CARE_LABELS)
    conn = _conn(db_path)
    try:
        with conn:
            handled = conn.execute(
                f"DELETE FROM audience_comments WHERE label IN ({care}) AND status!='new' AND COALESCE(handled_at, collected_at)<?", (cutoff,)
            ).rowcount
            other = conn.execute(f"DELETE FROM audience_comments WHERE label NOT IN ({care}) AND collected_at<?", (cutoff,)).rowcount
            conn.execute("DELETE FROM audience_posts WHERE post_url NOT IN (SELECT DISTINCT post_url FROM audience_comments) AND last_collected_at<?", (cutoff,))
    finally:
        conn.close()
    return {"handled_care_items": handled, "other_comments": other}


def forget_user(platform: str, username: str, db_path: Optional[str] = None) -> int:
    """Erase everything held about one commenter (a 'please delete my comments' request)."""
    conn = _conn(db_path)
    try:
        with conn:
            return conn.execute(
                "DELETE FROM audience_comments WHERE platform=? AND LOWER(username)=?", (platform.lower(), username.lstrip("@").strip().lower())
            ).rowcount
    finally:
        conn.close()


def stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = _conn(db_path)
    try:
        by_label = {r["label"]: r["n"] for r in conn.execute("SELECT label, COUNT(*) AS n FROM audience_comments GROUP BY label")}
        care = ",".join(f"'{l}'" for l in CARE_LABELS)
        waiting = {r["label"]: r["n"] for r in conn.execute(
            f"SELECT label, COUNT(*) AS n FROM audience_comments WHERE status='new' AND label IN ({care}) GROUP BY label")}
        oldest = conn.execute(
            f"SELECT MIN(COALESCE(created_at, collected_at)) AS t FROM audience_comments WHERE status='new' AND label IN ({care})").fetchone()["t"]
        posts = conn.execute("SELECT COUNT(*) AS n FROM audience_posts").fetchone()["n"]
        total = conn.execute("SELECT COUNT(*) AS n FROM audience_comments").fetchone()["n"]
    finally:
        conn.close()
    return {"comments": total, "posts": posts, "by_label": by_label, "waiting_for_a_reply": waiting, "oldest_waiting": oldest}
