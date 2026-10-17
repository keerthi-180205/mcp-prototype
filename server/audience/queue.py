"""The care queue as people (and, redacted, the assistant) see it."""

import datetime
from typing import Any, Dict, List, Optional, Sequence

from server.audience.templates import reply_draft
from server.storage import audience as store


def _hours_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        then = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if then.tzinfo is None:
            then = then.replace(tzinfo=datetime.timezone.utc)
        return round((datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() / 3600, 1)
    except ValueError:
        return None


def view(row: Dict[str, Any], with_text: bool) -> Dict[str, Any]:
    """with_text=True is for the reviewer's own screen; the assistant gets the redacted view, so a commenter's
    words and username never reach a third-party model just to route a queue."""
    out = {
        "key": row["comment_key"], "platform": row["platform"], "account": row["account"], "post_url": row["post_url"],
        "label": row["label"], "priority": row["priority"], "possible_minor": row["possible_minor"], "status": row["status"],
        "waiting_hours": _hours_since(row["created_at"] or row["collected_at"]),
    }
    if with_text:
        out.update(
            username=row["username"], comment=row["comment"], created_at=row["created_at"], reasons=row["reasons"],
            handled_by=row["handled_by"], handler_note=row["handler_note"], **reply_draft(row["label"], row["username"], row["possible_minor"]),
        )
    return out


def queue_items(statuses: Sequence[str] = ("new",), labels: Optional[Sequence[str]] = None, limit: int = 50, platform: Optional[str] = None,
                account: Optional[str] = None, with_text: bool = True, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    return [view(r, with_text) for r in store.list_queue(statuses, labels, limit, platform, account, db_path)]


def handle_item(key: str, status: str, handled_by: str = "", note: str = "", db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    row = store.set_status(key, status, handled_by, note, db_path)
    return view(row, with_text=False) if row else None
