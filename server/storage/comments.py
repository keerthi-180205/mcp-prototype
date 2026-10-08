"""SQLite persistence for collection jobs and collected commenter rows."""

import json
import sqlite3
from typing import Any, Dict, List, Optional

from server.collection.cleaning import norm_text, norm_username
from server.collection.models import CommentRow
from server.storage.sqlite import get_connection


def init_comment_tables(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_jobs (
                    job_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    config_json TEXT,
                    progress_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS collected_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    user_id TEXT,
                    comment TEXT NOT NULL,
                    likes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    post_url TEXT NOT NULL,
                    user_key TEXT NOT NULL,
                    comment_key TEXT NOT NULL,
                    UNIQUE(job_id, platform, user_key, comment_key)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_job ON collected_comments(job_id, platform)")
    finally:
        conn.close()


def create_job(job_id: str, topic: str, created_at: str, config: Dict[str, Any], db_path: Optional[str] = None) -> None:
    init_comment_tables(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO collection_jobs (job_id, topic, status, created_at, config_json) "
                "VALUES (?, ?, 'running', ?, ?)",
                (job_id, topic, created_at, json.dumps(config)),
            )
    finally:
        conn.close()


def update_job(
    job_id: str,
    status: str,
    progress: Dict[str, Any],
    finished_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE collection_jobs SET status=?, progress_json=?, finished_at=COALESCE(?, finished_at) "
                "WHERE job_id=?",
                (status, json.dumps(progress), finished_at, job_id),
            )
    finally:
        conn.close()


def get_job(job_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init_comment_tables(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM collection_jobs WHERE job_id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    data = dict(row)
    data["config"] = json.loads(data.pop("config_json") or "{}")
    data["progress"] = json.loads(data.pop("progress_json") or "{}")
    return data


def save_comments(job_id: str, rows: List[CommentRow], db_path: Optional[str] = None) -> int:
    """Insert rows, ignoring duplicates on (job, platform, username, comment). Returns rows inserted."""
    if not rows:
        return 0
    init_comment_tables(db_path)
    conn = get_connection(db_path)
    inserted = 0
    try:
        with conn:
            for r in rows:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO collected_comments "
                    "(job_id, platform, username, user_id, comment, likes, created_at, post_url, user_key, comment_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        job_id, r.platform, r.username, r.user_id, r.comment, r.likes, r.created_at,
                        r.post_url, norm_username(r.username), norm_text(r.comment).lower(),
                    ),
                )
                inserted += cur.rowcount
    finally:
        conn.close()
    return inserted


_COLS = "platform, username, user_id, comment, likes, created_at, post_url"


def get_comments(
    job_id: str,
    platform: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    init_comment_tables(db_path)
    conn = get_connection(db_path)
    try:
        sql = f"SELECT {_COLS} FROM collected_comments WHERE job_id=?"
        params: List[Any] = [job_id]
        if platform:
            sql += " AND platform=?"
            params.append(platform)
        sql += " ORDER BY id LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def iter_all_comments(job_id: str, db_path: Optional[str] = None, chunk: int = 1000):
    offset = 0
    while True:
        batch = get_comments(job_id, offset=offset, limit=chunk, db_path=db_path)
        if not batch:
            return
        yield from batch
        offset += len(batch)


def count_by_platform(job_id: str, db_path: Optional[str] = None) -> Dict[str, int]:
    init_comment_tables(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT platform, COUNT(*) AS n FROM collected_comments WHERE job_id=? GROUP BY platform", (job_id,)
        ).fetchall()
        return {r["platform"]: r["n"] for r in rows}
    finally:
        conn.close()


def top_comments(job_id: str, per_platform: int = 3, db_path: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    init_comment_tables(db_path)
    conn = get_connection(db_path)
    try:
        for plat in count_by_platform(job_id, db_path):
            rows = conn.execute(
                f"SELECT {_COLS} FROM collected_comments WHERE job_id=? AND platform=? "
                "ORDER BY likes DESC, id LIMIT ?",
                (job_id, plat, per_platform),
            ).fetchall()
            out[plat] = [dict(r) for r in rows]
    finally:
        conn.close()
    return out
