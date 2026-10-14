"""CSV of the comments collected from MMTF's own posts (usernames + what they said + the triage label)."""

import csv
import datetime
import os
from typing import Any, Dict, Optional, Sequence

from server.csv_safe import safe_row
from server.storage import audience as store

FIELDS = ["platform", "account", "post_url", "username", "comment", "likes", "created_at", "label", "possible_minor", "generic",
          "reasons", "status", "handled_by", "handler_note"]


def export_audience(platform: Optional[str] = None, account: Optional[str] = None, labels: Optional[Sequence[str]] = None,
                    post_urls: Optional[Sequence[str]] = None, out_dir: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    from server.collection import export as collection_export  # read at call time so tests can redirect it

    out_dir = out_dir or collection_export.DEFAULT_EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    rows = store.list_comments(platform, account, labels, post_urls, db_path)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"own_audience_{platform or 'all'}_{stamp}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(safe_row({**r, "reasons": "; ".join(r["reasons"])}))
    return {"path": path, "rows": len(rows), "contains_personal_data": True}
