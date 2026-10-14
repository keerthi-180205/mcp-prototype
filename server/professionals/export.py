"""CSV / JSON export of reviewed professionals."""

import csv
import datetime
import json
import os
from typing import Any, Dict, Optional, Sequence

from server.storage import professionals as store

FIELDS = [
    "pro_id", "name", "entity_type", "role", "confidence", "credentials", "evidence", "city", "headline",
    "profile_url", "website_url", "followers",
    "best_channel", "best_channel_value", "best_channel_source",
    "email", "email_is_generic", "phone", "whatsapp", "contact_form", "instagram", "linkedin",
    "licence_claim", "licence_numbers", "licence_verified", "review_status", "review_note",
    "first_seen_at", "last_seen_at", "all_channels",
]


def export_professionals(
    statuses: Sequence[str] = ("approved",),
    fmt: str = "csv",
    out_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Write reviewed professionals to data/exports. do_not_contact and suppressed people are never included."""
    fmt = fmt.lower().strip()
    if fmt not in ("csv", "json"):
        raise ValueError("format must be 'csv' or 'json'")
    bad = [s for s in statuses if s not in store.REVIEW_STATUSES]
    if bad:
        raise ValueError(f"unknown status {bad}; choose from {list(store.REVIEW_STATUSES)}")
    from server.collection import export as collection_export  # read at call time so tests can redirect it

    out_dir = out_dir or collection_export.DEFAULT_EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    rows = store.export_rows(statuses, db_path)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"professionals_{'-'.join(statuses)}_{stamp}.{fmt}")
    if fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads non-Latin names
            writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([{k: r.get(k) for k in FIELDS + ["channels"]} for r in rows], fh, ensure_ascii=False, indent=2)
    return {"path": path, "format": fmt, "rows": len(rows), "statuses": list(statuses)}
