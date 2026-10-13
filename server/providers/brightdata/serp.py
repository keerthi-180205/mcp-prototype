"""Bright Data SERP API client: Google results as parsed JSON.

    POST {base}/request   {"zone": <serp zone>, "url": "https://www.google.com/search?...&brd_json=1", "format": "raw"}

Verified live (Oct 2026). Two things to know:

* The HTTP status is 200 even when the search itself failed. The real outcome is in the
  `x-brd-status-code` / `x-brd-error-code` response headers (for example 502 + "captcha" with an
  empty body). Failed requests are not billed, and a captcha is usually gone on the next try.
* A search with no results is a success (empty `organic`), and is billed.
"""

import asyncio
import datetime
import logging
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from server.config import Settings, get_settings

logger = logging.getLogger("mcp_server.providers.brightdata.serp")

SEARCH_URL = "https://www.google.com/search"
MAX_ATTEMPTS = 3
# Upstream statuses that retrying cannot fix (bad query, blocked parameter, missing page). Everything
# else - captcha (502), "failed_query_rejected" (429), timeouts - is transient and is retried.
PERMANENT_UPSTREAM = {"400", "401", "403", "404", "410", "422"}


class BrightDataSerpError(Exception):
    """A search failed (captcha that did not clear, upstream error, unparseable response)."""


class BrightDataSerpAuthError(BrightDataSerpError):
    """Bad API key, or the zone does not exist / is not a SERP zone. Retrying will not help."""


@dataclass
class SerpResult:
    rank: int
    url: str
    title: str = ""
    snippet: str = ""
    source: str = ""   # e.g. "Instagram · dr.jud", "X · anishmoonka", "LinkedIn · Clarissa S"
    display: str = ""  # e.g. "4.9K+ likes · 20 hours ago", "460+ followers"


@dataclass
class SerpPage:
    query: str
    results: List[SerpResult] = field(default_factory=list)
    next_start: Optional[int] = None  # `start` value of the following page, if there is one
    total: Optional[int] = None       # Google's estimated result count
    # True when the query asked for `site:<domain>` but most results are from elsewhere: Google
    # intermittently ignores the operator and Bright Data still bills the page as a success.
    degraded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SerpPage":
        return cls(
            query=data.get("query", ""),
            results=[SerpResult(**r) for r in data.get("results", [])],
            next_start=data.get("next_start"),
            total=data.get("total"),
            degraded=bool(data.get("degraded", False)),
        )


# ---- parsing helpers for Google's "4.9K+ likes · 20 hours ago" style line ------------------
_LIKES = re.compile(r"([\d][\d.,]*)\s*([KkMm]?)\+?\s+likes?\b")
_AGE = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE)
_UNIT_SECONDS = {
    "second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400,
    "month": 30 * 86400, "year": 365 * 86400,
}


def parse_likes(display: str) -> Optional[int]:
    m = _LIKES.search(display or "")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(value * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()])


def parse_age(display: str, now: Optional[datetime.datetime] = None) -> Optional[str]:
    """ISO timestamp for "3 months ago" style text. Approximate by nature: Google only gives a coarse age."""
    m = _AGE.search(display or "")
    if not m:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()])).isoformat()


_SITE = re.compile(r"\bsite:([^\s/]+)", re.IGNORECASE)


def matches_site(query: str, url: str) -> bool:
    """False only when the query has a `site:` filter and this URL is not on that domain."""
    m = _SITE.search(query or "")
    if not m:
        return True
    domain = m.group(1).lower().lstrip(".")
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return host == domain or host.endswith("." + domain)


def ignored_site_operator(query: str, results: List[SerpResult]) -> bool:
    """True if the query has a `site:` filter that fewer than half of the results satisfy."""
    if not _SITE.search(query or "") or not results:
        return False
    return sum(matches_site(query, r.url) for r in results) * 2 < len(results)


class BrightDataSerpClient:
    DEFAULT_TIMEOUT = 90.0  # a SERP call can include captcha solving

    def __init__(
        self,
        api_key: Optional[str] = None,
        zone: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
        retry_delay: float = 1.0,
    ) -> None:
        cfg = settings or get_settings()
        self._api_key = api_key or cfg.brightdata_api_key
        self.zone = zone or cfg.brightdata_serp_zone
        self.country = cfg.brightdata_serp_country
        self.base_url = (base_url or cfg.brightdata_base_url or "https://api.brightdata.com").rstrip("/")
        self.timeout = timeout if timeout is not None else max(cfg.brightdata_timeout, self.DEFAULT_TIMEOUT)
        self._client = client
        self.retry_delay = retry_delay

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip() and self.zone and self.zone.strip())

    def not_configured_reason(self) -> str:
        if not (self._api_key and self._api_key.strip()):
            return "BRIGHTDATA_API_KEY is not set"
        return "BRIGHTDATA_SERP_ZONE is not set (use the name of your SERP API zone from the Bright Data control panel)"

    def search_url(self, query: str, start: int = 0, tbs: Optional[str] = None, country: Optional[str] = None,
                   language: str = "en") -> str:
        params: Dict[str, Any] = {"q": query, "hl": language, "brd_json": "1"}
        country = country or self.country
        if country:
            params["gl"] = country.lower()
        if start:
            params["start"] = start
        if tbs:  # e.g. "qdr:m" = past month, "qdr:y" = past year
            params["tbs"] = tbs
        return f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"

    async def search(self, query: str, start: int = 0, tbs: Optional[str] = None,
                     country: Optional[str] = None, language: str = "en") -> SerpPage:
        if not self.is_configured:
            raise BrightDataSerpAuthError(self.not_configured_reason())

        body = {"zone": self.zone, "url": self.search_url(query, start, tbs, country, language), "format": "raw"}
        headers = {"Authorization": f"Bearer {self._api_key.strip()}", "Content-Type": "application/json"}
        http = self._client if self._client is not None and not self._client.is_closed else httpx.AsyncClient()
        owns = http is not self._client
        last = ""
        attempts = 0
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                attempts = attempt
                try:
                    resp = await http.post(f"{self.base_url}/request", json=body, headers=headers, timeout=self.timeout)
                except httpx.TimeoutException as exc:
                    last = f"timed out: {exc}"
                except httpx.RequestError as exc:
                    last = f"network error: {exc}"
                else:
                    if resp.status_code in (401, 403):
                        raise BrightDataSerpAuthError(f"Bright Data rejected the API key (HTTP {resp.status_code})")
                    if resp.status_code in (400, 404, 422) and "zone" in resp.text.lower():
                        raise BrightDataSerpAuthError(f"Bright Data zone problem for {self.zone!r}: {resp.text[:160]}")
                    status = resp.headers.get("x-brd-status-code", str(resp.status_code))
                    error = resp.headers.get("x-brd-error-code") or resp.headers.get("x-brd-error")
                    if resp.status_code < 400 and status == "200" and not error:
                        return self._parse(query, resp)
                    last = f"HTTP {resp.status_code}, upstream {status}" + (f" ({error})" if error else "")
                    if status in PERMANENT_UPSTREAM:
                        break
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(self.retry_delay * attempt)
        finally:
            if owns:
                await http.aclose()
        raise BrightDataSerpError(f"SERP search failed after {attempts} attempt(s): {last}")

    @staticmethod
    def _parse(query: str, resp: httpx.Response) -> SerpPage:
        try:
            data = resp.json()
        except ValueError as exc:
            raise BrightDataSerpError("SERP response was not JSON") from exc
        if not isinstance(data, dict):
            raise BrightDataSerpError("SERP response had an unexpected shape")

        results: List[SerpResult] = []
        for i, item in enumerate(data.get("organic") or [], 1):
            url = item.get("link")
            if not url:
                continue
            results.append(SerpResult(
                rank=int(item.get("rank") or i),
                url=url,
                title=(item.get("title") or "").strip(),
                snippet=(item.get("description") or "").strip(),
                source=(item.get("source") or "").strip(),
                display=(item.get("display_link") or "").strip(),
            ))
        pagination = data.get("pagination") or {}
        general = data.get("general") or {}
        return SerpPage(
            query=query,
            results=results,
            next_start=pagination.get("next_page_start"),
            total=general.get("results_cnt"),
            degraded=ignored_site_operator(query, results),
        )
