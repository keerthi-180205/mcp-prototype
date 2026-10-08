"""CSV / JSON export of collected comment rows."""

import csv
import json
import os
from typing import Dict, Optional

from server.storage.comments import iter_all_comments

FIELDS = ["platform", "username", "user_id", "comment", "likes", "created_at", "post_url"]

DEFAULT_EXPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "exports"
)


def export_job(job_id: str, fmt: str = "csv", out_dir: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, object]:
    """Write all rows of a job to `<out_dir>/<job_id>.<fmt>` and return path + row count."""
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
            writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in iter_all_comments(job_id, db_path=db_path):
                writer.writerow(row)
                count += 1
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[")
            for row in iter_all_comments(job_id, db_path=db_path):
                fh.write(("," if count else "") + "\n  " + json.dumps({k: row.get(k) for k in FIELDS}, ensure_ascii=False))
                count += 1
            fh.write("\n]\n")
    return {"path": path, "format": fmt, "rows": count}
