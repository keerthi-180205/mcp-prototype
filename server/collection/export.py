"""CSV / JSON export of collected comment rows."""

import csv
import json
import os
from typing import Dict, Optional

from server.csv_safe import safe_row
from server.storage.comments import iter_all_comments

import datetime
import re
from typing import Any, List, Optional

from server.collection.models import CommentRow
from server.storage.comments import create_job, iter_all_comments, save_comments

FIELDS = ["platform", "username", "user_id", "comment", "likes", "created_at", "post_url"]
# Optional provenance columns: which provider served the row, thread ids and collection time.
FIELDS_FULL = FIELDS + ["provider", "comment_id", "parent_id", "collected_at"]
SCRAPED_CSV_FIELDS = ["platform", "username", "user_id", "comment", "likes", "created_at", "post_url", "category", "topic"]

DEFAULT_EXPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "exports"
)


def export_job(
    job_id: str, fmt: str = "csv", out_dir: Optional[str] = None, db_path: Optional[str] = None, full: bool = False
) -> Dict[str, object]:
    """Write all rows of a job to `<out_dir>/<job_id>.<fmt>` and return path + row count.

    `full=True` adds the provenance columns (provider, comment_id, parent_id, collected_at).
    """
    fields = FIELDS_FULL if full else FIELDS
    fmt = fmt.lower().strip()
    if fmt not in ("csv", "json"):
        raise ValueError("format must be 'csv' or 'json'")
    out_dir = out_dir or DEFAULT_EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{job_id}.{fmt}")

    count = 0
    if fmt == "csv":
        # utf-8-sig so Excel opens emoji / non-Latin text correctly
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in iter_all_comments(job_id, db_path=db_path):
                writer.writerow(safe_row(row))
                count += 1
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[")
            for row in iter_all_comments(job_id, db_path=db_path):
                fh.write(("," if count else "") + "\n  " + json.dumps({k: row.get(k) for k in fields}, ensure_ascii=False))
                count += 1
            fh.write("\n]\n")
    return {"path": path, "format": fmt, "rows": count}


def save_scraped_comments_to_csv(
    comments: List[Dict[str, Any]],
    topic: str = "scraped_data",
    job_id: Optional[str] = None,
    out_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Save freshly scraped comments across Instagram, LinkedIn, X, Reddit, YouTube to CSV files.

    Writes:
      1. Specific topic timestamped file: `<out_dir>/scraped_<slug>_<timestamp>.csv`
      2. Convenience pointer: `<out_dir>/latest_scraped_comments.csv`
      3. Persists rows into SQLite collected_comments table under `job_id`.
    """
    out_dir = out_dir or DEFAULT_EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)

    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_topic = re.sub(r"[^a-zA-Z0-9_\-]+", "_", topic.strip().lower())[:40] or "comments"
    filename = f"scraped_{clean_topic}_{now_str}.csv"
    path = os.path.join(out_dir, filename)
    latest_path = os.path.join(out_dir, "latest_scraped_comments.csv")

    normalized_rows: List[Dict[str, Any]] = []
    comment_rows_for_db: List[CommentRow] = []

    for c in comments:
        plat = str(c.get("platform") or "unknown").lower()
        uname = str(c.get("username") or c.get("user_handle") or c.get("author_username") or "").strip()
        uid = str(c.get("user_id") or "")
        body = str(c.get("comment") or c.get("comment_text") or c.get("text") or "").strip()
        likes = int(c.get("likes") or c.get("like_count") or 0)
        created = str(c.get("created_at") or c.get("published_at") or "")
        post_url = str(c.get("post_url") or c.get("url") or "")
        cat = str(c.get("category") or "")
        top = str(c.get("topic") or topic)

        row_dict = {
            "platform": plat,
            "username": uname,
            "user_id": uid,
            "comment": body,
            "likes": likes,
            "created_at": created,
            "post_url": post_url,
            "category": cat,
            "topic": top,
        }
        normalized_rows.append(row_dict)

        if body:
            comment_rows_for_db.append(
                CommentRow(
                    platform=plat,
                    username=uname or "user",
                    user_id=uid,
                    comment=body,
                    likes=likes,
                    created_at=created or None,
                    post_url=post_url,
                )
            )

    # Save to both topic timestamped CSV and latest_scraped_comments.csv
    for out_file in (path, latest_path):
        with open(out_file, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=SCRAPED_CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for r in normalized_rows:
                writer.writerow(safe_row(r))

    # Persist into database so comments are searchable, exportable by job, and deduplicated
    db_job_id = job_id or f"job_chat_{now_str}"
    try:
        create_job(
            db_job_id,
            topic=topic,
            created_at=datetime.datetime.now().isoformat(),
            config={"source": "chat_discovery", "topic": topic},
            db_path=db_path,
        )
        if comment_rows_for_db:
            save_comments(db_job_id, comment_rows_for_db, db_path=db_path)
    except Exception:
        pass

    return {
        "path": path,
        "latest_path": latest_path,
        "filename": filename,
        "rows": len(normalized_rows),
        "topic": topic,
        "job_id": db_job_id,
    }


def export_all_scraped_comments(out_dir: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Export every collected comment across all jobs in SQLite to all_scraped_comments.csv."""
    out_dir = out_dir or DEFAULT_EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "all_scraped_comments.csv")

    count = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in iter_all_comments("all", db_path=db_path):
            writer.writerow(safe_row(row))
            count += 1

    return {"path": path, "filename": "all_scraped_comments.csv", "rows": count}

