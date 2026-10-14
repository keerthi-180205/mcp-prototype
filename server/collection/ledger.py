"""Persistent provider ledger: response cache, usage log and spending budgets.

Paid providers (TrueScrape, SocialCrawl, Apify) charge per call, so every paid call goes through
this ledger:

* `cache_get` / `cache_put` - responses are kept in SQLite, so re-running a topic or restarting
  the server never pays twice for the same post or profile.
* `record_usage` - an audit row per call (credits, cost, cache hit, error).
* `check_budget` - per-day and per-job limits taken from the environment. When one is reached the
  backend raises `BudgetExceeded` and the chain moves to the next provider.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from server.storage.sqlite import get_connection

logger = logging.getLogger("mcp_server.collection.ledger")

# Default limits, in provider credits (Apify is limited in USD elsewhere). Override per provider
# with BUDGET_<PROVIDER>_PER_DAY / BUDGET_<PROVIDER>_PER_JOB; 0 means unlimited.
DEFAULT_BUDGETS = {
    "truescrape": {"per_day": 200, "per_job": 60},
    "socialcrawl": {"per_day": 100, "per_job": 30},
    # Bright Data's free pool is 5,000 credits a month shared by SERP / Unlocker / Web Scraper.
    "brightdata": {"per_day": 150, "per_job": 40},
}

DEFAULT_CACHE_TTL = 24 * 3600
DEFAULT_BLOCK_TTL = 1800            # transient trouble: look again in 30 minutes
NO_CREDIT_BLOCK_TTL = 6 * 3600      # no credits / bad key does not fix itself: remember for 6 hours (or until the key changes)


class BudgetExceeded(Exception):
    """A provider's per-day or per-job credit limit has been reached."""


def get_budget(provider: str) -> Dict[str, int]:
    base = DEFAULT_BUDGETS.get(provider, {"per_day": 0, "per_job": 0})
    out = {}
    for key in ("per_day", "per_job"):
        raw = os.getenv(f"BUDGET_{provider.upper()}_{key.upper()}")
        try:
            out[key] = int(raw) if raw not in (None, "") else base[key]
        except ValueError:
            out[key] = base[key]
    return out


class ProviderLedger:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._ready = False

    # ---- schema --------------------------------------------------------------------
    def _conn(self):
        conn = get_connection(self.db_path)
        if not self._ready:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS provider_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        provider TEXT NOT NULL,
                        platform TEXT NOT NULL DEFAULT '',
                        action TEXT NOT NULL DEFAULT '',
                        credits REAL NOT NULL DEFAULT 0,
                        cost_usd REAL NOT NULL DEFAULT 0,
                        cached INTEGER NOT NULL DEFAULT 0,
                        ok INTEGER NOT NULL DEFAULT 1,
                        detail TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_pu_provider_ts ON provider_usage(provider, ts)")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_cache (
                        cache_key TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )
            self._ready = True
        return conn

    # ---- cache ---------------------------------------------------------------------
    def cache_get(self, key: str) -> Optional[Any]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT value_json FROM api_cache WHERE cache_key=? AND expires_at>?", (key, time.time())
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row["value_json"]) if row else None

    def cache_put(self, key: str, provider: str, value: Any, ttl: float = DEFAULT_CACHE_TTL) -> None:
        now = time.time()
        conn = self._conn()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO api_cache (cache_key, provider, value_json, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (key, provider, json.dumps(value, default=str), now, now + ttl),
                )
        finally:
            conn.close()

    # ---- blocked providers ---------------------------------------------------------
    def set_blocked(self, provider: str, reason: str, ttl: float = DEFAULT_BLOCK_TTL, fingerprint: Optional[str] = None) -> None:
        """Remember that a provider is unusable (no credits, bad key) so jobs stop retrying it and the UI can say why.
        `fingerprint` identifies the API key in use: if the key changes the block no longer applies."""
        self.cache_put(f"blocked|{provider}", provider, {"reason": reason[:200], "fp": fingerprint}, ttl)

    def blocked_reason(self, provider: str, fingerprint: Optional[str] = None) -> Optional[str]:
        state = self.cache_get(f"blocked|{provider}")
        if not state:
            return None
        if state.get("fp") and fingerprint and state["fp"] != fingerprint:
            return None  # a different key than the one that failed
        return state["reason"]

    def clear_blocked(self, provider: str) -> bool:
        """Forget a block, e.g. right after topping up credits. Returns True if there was one."""
        conn = self._conn()
        try:
            with conn:
                cur = conn.execute("DELETE FROM api_cache WHERE cache_key=?", (f"blocked|{provider}",))
            return cur.rowcount > 0
        finally:
            conn.close()

    # ---- usage ---------------------------------------------------------------------
    def record_usage(
        self,
        provider: str,
        platform: str,
        action: str,
        credits: float = 0,
        cost_usd: float = 0,
        cached: bool = False,
        ok: bool = True,
        detail: str = "",
    ) -> None:
        try:
            conn = self._conn()
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO provider_usage (ts, provider, platform, action, credits, cost_usd, cached, ok, detail) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (time.time(), provider, platform, action, credits, cost_usd, int(cached), int(ok), detail[:300]),
                    )
            finally:
                conn.close()
        except Exception:  # accounting must never break a collection
            logger.exception("Could not record provider usage")

    def spent_today(self, provider: str) -> float:
        since = time.time() - 24 * 3600
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(credits), 0) AS c FROM provider_usage WHERE provider=? AND ts>? AND cached=0",
                (provider, since),
            ).fetchone()
        finally:
            conn.close()
        return float(row["c"])

    def check_budget(self, provider: str, credits: float, spent_this_job: float) -> None:
        """Raise BudgetExceeded if spending `credits` more would break a limit."""
        budget = get_budget(provider)
        if budget["per_job"] and spent_this_job + credits > budget["per_job"]:
            raise BudgetExceeded(f"{provider}: per-job limit of {budget['per_job']} credits reached")
        if budget["per_day"] and self.spent_today(provider) + credits > budget["per_day"]:
            raise BudgetExceeded(f"{provider}: daily limit of {budget['per_day']} credits reached")

    def summary(self, days: int = 1) -> Dict[str, Any]:
        since = time.time() - days * 24 * 3600
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT provider, platform, COUNT(*) AS calls, SUM(cached) AS cache_hits, "
                "SUM(CASE WHEN cached=0 THEN credits ELSE 0 END) AS credits, SUM(cost_usd) AS cost_usd, "
                "SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS errors "
                "FROM provider_usage WHERE ts>? GROUP BY provider, platform",
                (since,),
            ).fetchall()
        finally:
            conn.close()
        providers: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            p = providers.setdefault(
                r["provider"],
                {"calls": 0, "cache_hits": 0, "credits": 0.0, "cost_usd": 0.0, "errors": 0, "platforms": {}, "budget": get_budget(r["provider"])},
            )
            p["calls"] += r["calls"]
            p["cache_hits"] += r["cache_hits"] or 0
            p["credits"] += r["credits"] or 0
            p["cost_usd"] = round(p["cost_usd"] + (r["cost_usd"] or 0), 4)
            p["errors"] += r["errors"] or 0
            p["platforms"][r["platform"]] = r["calls"]
        for name in DEFAULT_BUDGETS:
            providers.setdefault(
                name,
                {"calls": 0, "cache_hits": 0, "credits": 0.0, "cost_usd": 0.0, "errors": 0, "platforms": {}, "budget": get_budget(name)},
            )
        return {"window_days": days, "providers": providers}


def get_ledger(db_path: Optional[str] = None) -> ProviderLedger:
    return ProviderLedger(db_path)


def cache_key(provider: str, *parts: Any) -> str:
    return provider + "|" + "|".join(str(p) for p in parts)
