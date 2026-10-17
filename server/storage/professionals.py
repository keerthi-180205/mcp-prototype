"""SQLite persistence for the professional finder: runs, professionals, channels, suppression list."""

import datetime
import hashlib
import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from server.professionals.models import REVIEW_STATUSES, Channel, Licence, ProfessionalRecord
from server.storage.sqlite import get_connection

SUPPRESSION_KINDS = ("email", "phone", "domain", "profile_url")
# Shared mail providers: suppressing "gmail.com" would silence millions of unrelated people.
FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "rediffmail.com", "protonmail.com", "proton.me", "aol.com", "msn.com", "zoho.com", "mail.com",
}
_SORTS = {
    "fit_score": "p.fit_score DESC, p.confidence DESC",
    "confidence": "p.confidence DESC, p.fit_score DESC",
    "recent": "p.last_seen_at DESC",
    "name": "p.name COLLATE NOCASE ASC",
}
_CHANNEL_FILTERS = {
    "email": "c.kind = 'email'",
    "personal_email": "c.kind = 'email' AND c.is_generic = 0",
    "phone": "c.kind = 'phone'",
    "contact_form": "c.kind = 'contact_form'",
    "any": "c.kind IN ('email', 'phone', 'whatsapp', 'contact_form')",
}
BEST_CHANNEL_ORDER = ("personal_email", "generic_email", "contact_form", "whatsapp", "phone", "instagram", "linkedin", "website")


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def pro_id_for(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def init_tables(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pro_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    progress_json TEXT,
                    stats_json TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS professionals (
                    pro_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0,
                    classified_by TEXT NOT NULL DEFAULT 'rules',
                    credentials_json TEXT NOT NULL DEFAULT '[]',
                    evidence TEXT NOT NULL DEFAULT '',
                    red_flags_json TEXT NOT NULL DEFAULT '[]',
                    needs_review_reason TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    city_match INTEGER NOT NULL DEFAULT 0,
                    headline TEXT NOT NULL DEFAULT '',
                    snippet TEXT NOT NULL DEFAULT '',
                    profile_url TEXT NOT NULL,
                    handle TEXT,
                    website_url TEXT,
                    followers INTEGER,
                    licence_claim TEXT NOT NULL DEFAULT '',
                    licence_numbers_json TEXT NOT NULL DEFAULT '[]',
                    licence_verified INTEGER,
                    fit_score REAL NOT NULL DEFAULT 0,
                    review_status TEXT NOT NULL DEFAULT 'new',
                    review_note TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT,
                    first_run_id TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pro_status ON professionals(review_status, fit_score);
                CREATE TABLE IF NOT EXISTS pro_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pro_id TEXT NOT NULL REFERENCES professionals(pro_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    is_generic INTEGER NOT NULL DEFAULT 0,
                    found_via TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    collected_at TEXT NOT NULL,
                    UNIQUE(pro_id, kind, value)
                );
                CREATE INDEX IF NOT EXISTS idx_pro_channels ON pro_channels(pro_id, kind);
                CREATE TABLE IF NOT EXISTS pro_enrich_log (
                    pro_id TEXT PRIMARY KEY,
                    attempted_at TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS pro_suppression (
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (kind, value)
                );
                """
            )
    finally:
        conn.close()


def _conn(db_path: Optional[str]) -> sqlite3.Connection:
    init_tables(db_path)
    return get_connection(db_path)


# ---- runs ----------------------------------------------------------------------------------------
def create_run(run_id: str, params: Dict[str, Any], db_path: Optional[str] = None) -> None:
    conn = _conn(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO pro_runs (run_id, created_at, status, params_json) VALUES (?, ?, 'running', ?)",
                (run_id, now_iso(), json.dumps(params)),
            )
    finally:
        conn.close()


def update_run(run_id: str, status: Optional[str] = None, progress: Optional[Dict[str, Any]] = None,
               stats: Optional[Dict[str, Any]] = None, error: Optional[str] = None, db_path: Optional[str] = None) -> None:
    conn = _conn(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE pro_runs SET status=COALESCE(?, status), progress_json=COALESCE(?, progress_json), "
                "stats_json=COALESCE(?, stats_json), error=COALESCE(?, error), "
                "finished_at=CASE WHEN ? IN ('completed', 'failed', 'interrupted') THEN ? ELSE finished_at END WHERE run_id=?",
                (status, json.dumps(progress) if progress is not None else None, json.dumps(stats) if stats is not None else None,
                 error, status, now_iso(), run_id),
            )
    finally:
        conn.close()


def get_run(run_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = _conn(db_path)
    try:
        row = conn.execute("SELECT * FROM pro_runs WHERE run_id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    for col in ("params", "progress", "stats"):
        d[col] = json.loads(d.pop(f"{col}_json") or "{}")
    return d


# ---- professionals ---------------------------------------------------------------------------------
def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["credentials"] = json.loads(d.pop("credentials_json") or "[]")
    d["red_flags"] = json.loads(d.pop("red_flags_json") or "[]")
    verified = d.pop("licence_verified")
    d["licence"] = {"claim": d.pop("licence_claim"), "numbers": json.loads(d.pop("licence_numbers_json") or "[]"),
                    "verified": None if verified is None else bool(verified)}
    d["city_match"] = bool(d["city_match"])
    return d


def upsert_professional(rec: ProfessionalRecord, run_id: Optional[str] = None, db_path: Optional[str] = None) -> bool:
    """Insert or refresh a professional. Returns True if it was new. A human's review decision is never touched."""
    conn = _conn(db_path)
    now = now_iso()
    try:
        with conn:
            old = conn.execute("SELECT * FROM professionals WHERE pro_id=?", (rec.pro_id,)).fetchone()
            if old is None:
                conn.execute(
                    "INSERT INTO professionals (pro_id, kind, entity_type, name, role, confidence, classified_by, credentials_json, "
                    "evidence, red_flags_json, needs_review_reason, city, city_match, headline, snippet, profile_url, handle, website_url, "
                    "followers, licence_claim, licence_numbers_json, fit_score, first_run_id, first_seen_at, last_seen_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rec.pro_id, rec.kind, rec.entity_type, rec.name, rec.role, rec.confidence, rec.classified_by,
                     json.dumps(rec.credentials), rec.evidence, json.dumps(rec.red_flags), rec.needs_review_reason, rec.city,
                     int(rec.city_match), rec.headline, rec.snippet, rec.profile_url, rec.handle, rec.website_url, rec.followers,
                     rec.licence.claim, json.dumps(rec.licence.numbers), rec.fit_score, run_id, now, now),
                )
                is_new = True
            else:
                better = rec.confidence >= old["confidence"]
                numbers = json.loads(old["licence_numbers_json"] or "[]")
                known = {(n["body"], n["number"]) for n in numbers}
                numbers += [n for n in rec.licence.numbers if (n["body"], n["number"]) not in known]
                conn.execute(
                    "UPDATE professionals SET name=?, entity_type=?, role=?, confidence=?, classified_by=?, credentials_json=?, evidence=?, "
                    "red_flags_json=?, needs_review_reason=?, city=?, city_match=?, headline=?, snippet=?, handle=?, website_url=?, followers=?, "
                    "licence_claim=?, licence_numbers_json=?, fit_score=?, last_seen_at=? WHERE pro_id=?",
                    (rec.name or old["name"],
                     rec.entity_type if better else old["entity_type"], rec.role if better else old["role"],
                     max(rec.confidence, old["confidence"]), rec.classified_by if better else old["classified_by"],
                     json.dumps(rec.credentials) if better else old["credentials_json"], rec.evidence if better else old["evidence"],
                     json.dumps(rec.red_flags) if better else old["red_flags_json"],
                     rec.needs_review_reason if better else old["needs_review_reason"],
                     rec.city or old["city"], int(rec.city_match or old["city_match"]), rec.headline or old["headline"],
                     rec.snippet or old["snippet"], rec.handle or old["handle"], rec.website_url or old["website_url"],
                     rec.followers if rec.followers is not None else old["followers"],
                     rec.licence.claim or old["licence_claim"], json.dumps(numbers), max(rec.fit_score, 0.0), now, rec.pro_id),
                )
                is_new = False
            for ch in rec.channels:
                conn.execute(
                    "INSERT OR IGNORE INTO pro_channels (pro_id, kind, value, is_generic, found_via, source_url, collected_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (rec.pro_id, ch.kind, ch.value, int(ch.is_generic), ch.found_via, ch.source_url, now),
                )
    finally:
        conn.close()
    return is_new


def _channels_for(conn: sqlite3.Connection, pro_ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {p: [] for p in pro_ids}
    if not pro_ids:
        return out
    marks = ",".join("?" * len(pro_ids))
    for r in conn.execute(f"SELECT * FROM pro_channels WHERE pro_id IN ({marks}) ORDER BY id", list(pro_ids)):
        out[r["pro_id"]].append({"kind": r["kind"], "value": r["value"], "is_generic": bool(r["is_generic"]),
                                 "found_via": r["found_via"], "source_url": r["source_url"], "collected_at": r["collected_at"]})
    return out


def _suppression(conn: sqlite3.Connection) -> Dict[str, Set[str]]:
    sets: Dict[str, Set[str]] = {k: set() for k in SUPPRESSION_KINDS}
    for r in conn.execute("SELECT kind, value FROM pro_suppression"):
        sets[r["kind"]].add(r["value"])
    return sets


def suppressed_reason(pro: Dict[str, Any], sets: Dict[str, Set[str]]) -> Optional[str]:
    """Why this professional must not be contacted, or None."""
    if pro["profile_url"].rstrip("/").lower() in sets["profile_url"]:
        return "profile_url"
    domains = set()
    if pro.get("website_url"):
        host = pro["website_url"].split("//", 1)[-1].split("/", 1)[0].lower()
        domains.add(host[4:] if host.startswith("www.") else host)
    for ch in pro.get("channels", []):
        if ch["kind"] == "email":
            if ch["value"] in sets["email"]:
                return "email"
            domains.add(ch["value"].split("@", 1)[1])
        elif ch["kind"] == "phone" and ch["value"] in sets["phone"]:
            return "phone"
    if any(d in sets["domain"] for d in domains if d not in FREEMAIL):
        return "domain"
    return None


def get_professional(pro_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = _conn(db_path)
    try:
        row = conn.execute("SELECT * FROM professionals WHERE pro_id=?", (pro_id,)).fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        d["channels"] = _channels_for(conn, [pro_id])[pro_id]
        d["suppressed"] = suppressed_reason(d, _suppression(conn))
        return d
    finally:
        conn.close()


def list_professionals(
    statuses: Optional[Iterable[str]] = None,
    role: Optional[str] = None,
    entity_type: Optional[str] = None,
    city: Optional[str] = None,
    min_confidence: float = 0.0,
    has_channel: Optional[str] = None,
    needs_review: Optional[bool] = None,
    q: Optional[str] = None,
    sort: str = "fit_score",
    limit: int = 25,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> Tuple[int, List[Dict[str, Any]]]:
    where, params = ["1=1"], []  # type: List[str], List[Any]
    if statuses:
        statuses = list(statuses)
        where.append(f"p.review_status IN ({','.join('?' * len(statuses))})")
        params += statuses
    if role:
        where.append("p.role = ?"); params.append(role)
    if entity_type:
        where.append("p.entity_type = ?"); params.append(entity_type)
    if city:
        where.append("lower(p.city) = lower(?)"); params.append(city)
    if min_confidence:
        where.append("p.confidence >= ?"); params.append(float(min_confidence))
    if has_channel:
        cond = _CHANNEL_FILTERS.get(has_channel)
        if cond is None:
            raise ValueError(f"has_channel must be one of {sorted(_CHANNEL_FILTERS)}")
        where.append(f"EXISTS (SELECT 1 FROM pro_channels c WHERE c.pro_id = p.pro_id AND {cond})")
    if needs_review is not None:
        where.append("p.needs_review_reason <> ''" if needs_review else "p.needs_review_reason = ''")
    if q:
        where.append("(p.name LIKE ? OR p.headline LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    order = _SORTS.get(sort, _SORTS["fit_score"])
    conn = _conn(db_path)
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM professionals p WHERE {' AND '.join(where)}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT p.* FROM professionals p WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [max(1, min(int(limit), 500)), max(0, int(offset))],
        ).fetchall()
        items = [_row_to_dict(r) for r in rows]
        chans = _channels_for(conn, [i["pro_id"] for i in items])
        sets = _suppression(conn)
        for i in items:
            i["channels"] = chans[i["pro_id"]]
            i["suppressed"] = suppressed_reason(i, sets)
        return total, items
    finally:
        conn.close()


def resolve_pro_id(prefix: str, db_path: Optional[str] = None) -> str:
    """Accept a unique prefix of a pro_id (at least 4 characters) and return the full id."""
    prefix = (prefix or "").strip().lower()
    if len(prefix) < 4:
        raise ValueError("give at least 4 characters of the id")
    conn = _conn(db_path)
    try:
        ids = [r[0] for r in conn.execute("SELECT pro_id FROM professionals WHERE pro_id LIKE ? LIMIT 3", (prefix.replace("%", "") + "%",))]
    finally:
        conn.close()
    if not ids:
        raise ValueError(f"no professional with id starting {prefix!r}")
    if len(ids) > 1:
        raise ValueError(f"id prefix {prefix!r} is ambiguous; type more characters")
    return ids[0]


def counts_by_status(db_path: Optional[str] = None) -> Dict[str, int]:
    conn = _conn(db_path)
    try:
        return {r["review_status"]: r["n"] for r in conn.execute("SELECT review_status, COUNT(*) AS n FROM professionals GROUP BY review_status")}
    finally:
        conn.close()


# ---- website-search attempts ------------------------------------------------------------------------------------
def last_enrich_attempt(pro_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, str]]:
    conn = _conn(db_path)
    try:
        row = conn.execute("SELECT attempted_at, outcome, detail FROM pro_enrich_log WHERE pro_id=?", (pro_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def log_enrich_attempt(pro_id: str, outcome: str, detail: str = "", db_path: Optional[str] = None) -> None:
    conn = _conn(db_path)
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO pro_enrich_log (pro_id, attempted_at, outcome, detail) VALUES (?,?,?,?)",
                         (pro_id, now_iso(), outcome, detail[:200]))
    finally:
        conn.close()


def reset_enrichment(pro_id: str, note: str, db_path: Optional[str] = None) -> None:
    """Undo a name-search website: its channels, the website link, the review note and the attempt record."""
    pro = get_professional(pro_id, db_path)
    if pro is None or not pro["website_url"]:
        return
    host = pro["website_url"].split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
    conn = _conn(db_path)
    try:
        with conn:
            for ch in pro["channels"]:
                src = (ch["source_url"] or "").split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
                if ch["found_via"] == "name_search" or (src == host and ch["found_via"] != "serp"):
                    conn.execute("DELETE FROM pro_channels WHERE pro_id=? AND kind=? AND value=?", (pro_id, ch["kind"], ch["value"]))
            reason = "; ".join(x for x in pro["needs_review_reason"].split("; ") if x and x != note)
            conn.execute("UPDATE professionals SET website_url=NULL, needs_review_reason=? WHERE pro_id=?", (reason, pro_id))
            conn.execute("DELETE FROM pro_enrich_log WHERE pro_id=?", (pro_id,))
    finally:
        conn.close()


# ---- review + suppression ---------------------------------------------------------------------------
def _norm_suppression(kind: str, value: str) -> str:
    value = (value or "").strip()
    if kind == "email":
        return value.lower()
    if kind == "phone":
        from server.professionals.web import normalize_phone
        return normalize_phone(value) or "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if kind == "domain":
        v = value.lower().split("@")[-1].split("//")[-1].split("/")[0]
        return v[4:] if v.startswith("www.") else v
    return value.rstrip("/").lower()


def add_suppression(kind: str, value: str, reason: str = "", db_path: Optional[str] = None) -> str:
    if kind not in SUPPRESSION_KINDS:
        raise ValueError(f"kind must be one of {list(SUPPRESSION_KINDS)}")
    norm = _norm_suppression(kind, value)
    if not norm:
        raise ValueError("value must not be empty")
    if kind == "domain" and norm in FREEMAIL:
        raise ValueError(f"{norm} is a shared mail provider; suppress the exact email address instead")
    conn = _conn(db_path)
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO pro_suppression (kind, value, reason, added_at) VALUES (?,?,?,?)",
                         (kind, norm, reason[:200], now_iso()))
    finally:
        conn.close()
    return norm


def remove_suppression(kind: str, value: str, db_path: Optional[str] = None) -> bool:
    conn = _conn(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM pro_suppression WHERE kind=? AND value=?", (kind, _norm_suppression(kind, value)))
        return cur.rowcount > 0
    finally:
        conn.close()


def list_suppression(db_path: Optional[str] = None) -> List[Dict[str, str]]:
    conn = _conn(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT kind, value, reason, added_at FROM pro_suppression ORDER BY added_at DESC")]
    finally:
        conn.close()


def set_review(pro_id: str, status: str, note: str = "", db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Record a human decision. `do_not_contact` also suppresses the person's profile, emails and phones for good."""
    if status not in REVIEW_STATUSES:
        raise ValueError(f"status must be one of {list(REVIEW_STATUSES)}")
    pro = get_professional(pro_id, db_path)
    if pro is None:
        return None
    conn = _conn(db_path)
    try:
        with conn:
            conn.execute("UPDATE professionals SET review_status=?, review_note=?, reviewed_at=? WHERE pro_id=?",
                         (status, note[:500], now_iso(), pro_id))
    finally:
        conn.close()
    if status == "do_not_contact":
        reason = f"do_not_contact via review of {pro_id}"
        add_suppression("profile_url", pro["profile_url"], reason, db_path)
        for ch in pro["channels"]:
            if ch["kind"] in ("email", "phone"):
                add_suppression(ch["kind"], ch["value"], reason, db_path)
    return get_professional(pro_id, db_path)


def set_licence_verified(pro_id: str, verified: Optional[bool], db_path: Optional[str] = None) -> None:
    """Set by a human after checking the official register (never by the finder)."""
    conn = _conn(db_path)
    try:
        with conn:
            conn.execute("UPDATE professionals SET licence_verified=? WHERE pro_id=?",
                         (None if verified is None else int(verified), pro_id))
    finally:
        conn.close()


# ---- export ----------------------------------------------------------------------------------------------
def best_channel(channels: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    def rank(ch: Dict[str, Any]) -> int:
        label = ("generic_email" if ch["is_generic"] else "personal_email") if ch["kind"] == "email" else ch["kind"]
        return BEST_CHANNEL_ORDER.index(label) if label in BEST_CHANNEL_ORDER else 99
    ranked = sorted(channels, key=rank)
    return ranked[0] if ranked and rank(ranked[0]) < 99 else None


def export_rows(statuses: Sequence[str] = ("approved",), db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Flat rows for outreach. Suppressed and do_not_contact people are never included."""
    _, items = list_professionals(statuses=[s for s in statuses if s != "do_not_contact"], limit=500, db_path=db_path)
    rows: List[Dict[str, Any]] = []
    for p in items:
        if p["suppressed"]:
            continue
        chans = p["channels"]
        emails = sorted((c for c in chans if c["kind"] == "email"), key=lambda c: c["is_generic"])
        best = best_channel(chans)
        first = lambda kind: next((c["value"] for c in chans if c["kind"] == kind), "")
        rows.append({
            "pro_id": p["pro_id"], "name": p["name"], "entity_type": p["entity_type"], "role": p["role"],
            "confidence": p["confidence"], "credentials": "; ".join(p["credentials"]), "evidence": p["evidence"],
            "city": p["city"], "headline": p["headline"], "profile_url": p["profile_url"], "website_url": p["website_url"] or "",
            "followers": p["followers"] if p["followers"] is not None else "",
            "best_channel": best["kind"] if best else "", "best_channel_value": best["value"] if best else "",
            "best_channel_source": best["source_url"] if best else "",
            "email": emails[0]["value"] if emails else "", "email_is_generic": emails[0]["is_generic"] if emails else "",
            "phone": first("phone"), "whatsapp": first("whatsapp"), "contact_form": first("contact_form"),
            "instagram": first("instagram"), "linkedin": first("linkedin"),
            "licence_claim": p["licence"]["claim"], "licence_numbers": "; ".join(f"{n['body']} {n['number']}" for n in p["licence"]["numbers"]),
            "licence_verified": "" if p["licence"]["verified"] is None else p["licence"]["verified"],
            "review_status": p["review_status"], "review_note": p["review_note"],
            "first_seen_at": p["first_seen_at"], "last_seen_at": p["last_seen_at"],
            "all_channels": " | ".join(f"{c['kind']}:{c['value']} <{c['source_url']}>" for c in chans),
            "channels": chans,
        })
    return rows
