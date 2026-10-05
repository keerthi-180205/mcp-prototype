"""SQLite storage and deduplication layer for normalized social intelligence records."""

import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialInteraction,
)

logger = logging.getLogger("mcp_server.storage.sqlite")

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "social_intelligence.db",
)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and return a database connection with row factory enabled."""
    target_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite tables and indexes for social intelligence deduplication and storage."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_records (
                    record_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    author_username TEXT,
                    author_user_id TEXT,
                    author_display_name TEXT,
                    author_profile_url TEXT,
                    is_verified INTEGER,
                    is_private INTEGER,
                    content_text TEXT,
                    content_title TEXT,
                    content_caption TEXT,
                    tags TEXT,
                    likes INTEGER,
                    comments_count INTEGER,
                    views INTEGER,
                    shares INTEGER,
                    published_at TEXT,
                    source_provider TEXT NOT NULL,
                    backend_tool TEXT,
                    fetched_at TEXT NOT NULL,
                    provider_metadata TEXT,
                    relevance_score REAL,
                    UNIQUE(platform, content_id)
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    interaction_id TEXT,
                    type TEXT NOT NULL DEFAULT 'comment',
                    text TEXT NOT NULL,
                    author_username TEXT,
                    author_user_id TEXT,
                    created_at TEXT,
                    likes INTEGER DEFAULT 0,
                    FOREIGN KEY (record_id) REFERENCES social_records (record_id) ON DELETE CASCADE,
                    UNIQUE(record_id, interaction_id)
                )
                """
            )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_platform ON social_records(platform)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_published_at ON social_records(published_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_relevance ON social_records(relevance_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_record ON social_interactions(record_id)")
    finally:
        conn.close()


def save_social_records(
    records: List[NormalizedSocialRecord], db_path: Optional[str] = None
) -> Dict[str, int]:
    """
    Save or upsert normalized records with deduplication on (platform, content_id).
    Also persists associated public interactions (comments).
    """
    init_db(db_path)
    conn = get_connection(db_path)
    inserted = 0
    updated = 0
    interactions_saved = 0

    try:
        with conn:
            for record in records:
                tags_json = json.dumps(record.content.tags or [])
                metadata_json = json.dumps(record.metadata.provider_metadata or {})

                # Check if record already exists
                cursor = conn.execute(
                    "SELECT record_id FROM social_records WHERE platform = ? AND content_id = ?",
                    (record.platform, record.content_id),
                )
                existing = cursor.fetchone()

                if existing:
                    # Update engagement and score
                    conn.execute(
                        """
                        UPDATE social_records
                        SET likes = ?,
                            comments_count = ?,
                            views = ?,
                            shares = ?,
                            content_text = COALESCE(?, content_text),
                            relevance_score = COALESCE(?, relevance_score),
                            fetched_at = ?
                        WHERE record_id = ?
                        """,
                        (
                            record.engagement.likes,
                            record.engagement.comments,
                            record.engagement.views,
                            record.engagement.shares,
                            record.content.text,
                            record.relevance_score,
                            record.metadata.fetched_at,
                            existing["record_id"],
                        ),
                    )
                    record_id = existing["record_id"]
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO social_records (
                            record_id, platform, content_type, content_id, source_url,
                            author_username, author_user_id, author_display_name, author_profile_url,
                            is_verified, is_private, content_text, content_title, content_caption,
                            tags, likes, comments_count, views, shares, published_at,
                            source_provider, backend_tool, fetched_at, provider_metadata, relevance_score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.record_id,
                            record.platform,
                            record.content_type,
                            record.content_id,
                            record.source_url,
                            record.author.username,
                            record.author.user_id,
                            record.author.display_name,
                            record.author.profile_url,
                            1 if record.author.is_verified else 0,
                            1 if record.author.is_private else 0,
                            record.content.text,
                            record.content.title,
                            record.content.caption,
                            tags_json,
                            record.engagement.likes,
                            record.engagement.comments,
                            record.engagement.views,
                            record.engagement.shares,
                            record.published_at,
                            record.metadata.source_provider,
                            record.metadata.backend_tool,
                            record.metadata.fetched_at,
                            metadata_json,
                            record.relevance_score,
                        ),
                    )
                    record_id = record.record_id
                    inserted += 1

                # Save public interactions / comments
                for inter in record.interactions:
                    inter_id = inter.interaction_id or f"hash_{hash(inter.text + str(inter.created_at))}"
                    try:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO social_interactions (
                                record_id, interaction_id, type, text,
                                author_username, author_user_id, created_at, likes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record_id,
                                inter_id,
                                inter.type,
                                inter.text,
                                inter.author.username,
                                inter.author.user_id,
                                inter.created_at,
                                inter.likes or 0,
                            ),
                        )
                        interactions_saved += 1
                    except sqlite3.Error as e:
                        logger.debug("Skipped duplicate or invalid interaction: %s", e)

        return {
            "inserted": inserted,
            "updated": updated,
            "total_processed": len(records),
            "interactions_saved": interactions_saved,
        }
    finally:
        conn.close()


def get_social_records(
    platform: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> List[NormalizedSocialRecord]:
    """Retrieve normalized social records from the database, ordered by recency and relevance."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM social_records WHERE 1=1"
        params: List[Any] = []

        if platform:
            query += " AND platform = ?"
            params.append(platform.lower())

        if topic:
            query += " AND (content_text LIKE ? OR content_title LIKE ? OR content_caption LIKE ? OR tags LIKE ?)"
            wildcard = f"%{topic}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        query += " ORDER BY published_at DESC, relevance_score DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        results: List[NormalizedSocialRecord] = []

        for row in rows:
            # Fetch interactions for this record
            int_rows = conn.execute(
                "SELECT * FROM social_interactions WHERE record_id = ? ORDER BY likes DESC",
                (row["record_id"],),
            ).fetchall()

            interactions = [
                SocialInteraction(
                    interaction_id=i["interaction_id"],
                    type=i["type"],
                    text=i["text"],
                    author=SocialAuthor(
                        username=i["author_username"],
                        user_id=i["author_user_id"],
                    ),
                    created_at=i["created_at"],
                    likes=i["likes"],
                )
                for i in int_rows
            ]

            tags = []
            if row["tags"]:
                try:
                    tags = json.loads(row["tags"])
                except Exception:
                    tags = []

            meta = {}
            if row["provider_metadata"]:
                try:
                    meta = json.loads(row["provider_metadata"])
                except Exception:
                    meta = {}

            record = NormalizedSocialRecord(
                record_id=row["record_id"],
                platform=row["platform"],
                content_type=row["content_type"],
                source_url=row["source_url"],
                content_id=row["content_id"],
                published_at=row["published_at"],
                author=SocialAuthor(
                    username=row["author_username"],
                    user_id=row["author_user_id"],
                    display_name=row["author_display_name"],
                    profile_url=row["author_profile_url"],
                    is_verified=bool(row["is_verified"]),
                    is_private=bool(row["is_private"]),
                ),
                content=SocialContent(
                    text=row["content_text"],
                    title=row["content_title"],
                    caption=row["content_caption"],
                    tags=tags,
                ),
                engagement=SocialEngagement(
                    likes=row["likes"],
                    comments=row["comments_count"],
                    views=row["views"],
                    shares=row["shares"],
                ),
                interactions=interactions,
                metadata=ProvenanceMetadata(
                    source_platform=row["platform"],
                    source_provider=row["source_provider"],
                    backend_tool=row["backend_tool"],
                    fetched_at=row["fetched_at"],
                    source_url=row["source_url"],
                    provider_metadata=meta,
                ),
                relevance_score=row["relevance_score"],
            )
            results.append(record)

        return results
    finally:
        conn.close()


def get_social_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Get aggregated statistics on stored social intelligence records."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        total_records = conn.execute("SELECT COUNT(*) FROM social_records").fetchone()[0]
        total_interactions = conn.execute("SELECT COUNT(*) FROM social_interactions").fetchone()[0]

        platform_rows = conn.execute(
            """
            SELECT platform, COUNT(*) as count, MAX(published_at) as latest
            FROM social_records
            GROUP BY platform
            """
        ).fetchall()

        platforms = {
            r["platform"]: {"count": r["count"], "latest_activity": r["latest"]}
            for r in platform_rows
        }

        return {
            "total_records": total_records,
            "total_interactions": total_interactions,
            "platforms": platforms,
        }
    finally:
        conn.close()
