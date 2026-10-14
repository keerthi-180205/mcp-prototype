"""Shared views for the REST API and the MCP tools, so both return the same shapes."""

from typing import Any, Dict, List, Optional

from server.storage import professionals as store

DECISIONS = {"approve": "approved", "approved": "approved", "reject": "rejected", "rejected": "rejected",
             "dnc": "do_not_contact", "do_not_contact": "do_not_contact", "new": "new", "reset": "new"}


def summarize(p: Dict[str, Any]) -> Dict[str, Any]:
    best = store.best_channel(p["channels"])
    return {
        "pro_id": p["pro_id"], "name": p["name"], "entity_type": p["entity_type"], "role": p["role"],
        "confidence": p["confidence"], "classified_by": p["classified_by"], "fit_score": p["fit_score"],
        "credentials": p["credentials"], "evidence": p["evidence"], "headline": p["headline"], "city": p["city"],
        "city_match": p["city_match"], "followers": p["followers"], "profile_url": p["profile_url"],
        "website_url": p["website_url"], "licence": p["licence"], "review_status": p["review_status"],
        "review_note": p["review_note"], "needs_review_reason": p["needs_review_reason"], "suppressed": p["suppressed"],
        "best_channel": {k: best[k] for k in ("kind", "value", "source_url", "is_generic")} if best else None,
        "channels": p["channels"], "first_seen_at": p["first_seen_at"], "last_seen_at": p["last_seen_at"],
    }


def list_view(
    db_path: Optional[str] = None,
    status: Optional[str] = "new",
    role: Optional[str] = None,
    entity_type: Optional[str] = None,
    city: Optional[str] = None,
    min_confidence: float = 0.0,
    has_channel: Optional[str] = None,
    needs_review: Optional[bool] = None,
    q: Optional[str] = None,
    sort: str = "fit_score",
    page: int = 1,
    page_size: int = 25,
) -> Dict[str, Any]:
    statuses: Optional[List[str]] = None
    if status and status != "all":
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in statuses if s not in store.REVIEW_STATUSES]
        if bad:
            raise ValueError(f"unknown status {bad}; choose from {list(store.REVIEW_STATUSES)} or 'all'")
    page, page_size = max(1, int(page)), max(1, min(int(page_size), 100))
    total, items = store.list_professionals(
        statuses=statuses, role=role, entity_type=entity_type, city=city, min_confidence=min_confidence,
        has_channel=has_channel, needs_review=needs_review, q=q, sort=sort,
        limit=page_size, offset=(page - 1) * page_size, db_path=db_path,
    )
    return {"total": total, "page": page, "page_size": page_size, "total_pages": max(1, -(-total // page_size)),
            "counts_by_review_status": store.counts_by_status(db_path), "items": [summarize(i) for i in items]}


def detail_view(pro_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    p = store.get_professional(pro_id, db_path)
    return summarize(p) if p else None


def review_view(pro_id: str, decision: str, note: str = "", licence_verified: Any = "unchanged",
                db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    status = DECISIONS.get((decision or "").strip().lower())
    if status is None:
        raise ValueError(f"decision must be one of {sorted(set(DECISIONS))}")
    if store.get_professional(pro_id, db_path) is None:
        return None
    if licence_verified != "unchanged":
        store.set_licence_verified(pro_id, licence_verified, db_path)
    return detail_view(store.set_review(pro_id, status, note or "", db_path)["pro_id"], db_path)
