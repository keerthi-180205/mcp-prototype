"""Bright Data API client for dataset scrapers and proxies.

Isolates HTTP communication with the Bright Data REST API (https://api.brightdata.com).
Authenticates via the 'Authorization: Bearer <key>' header.
Provides health inspection, dataset trigger execution, and snapshot retrieval.
"""

import logging
from typing import Any, Dict, List, Optional
import httpx

from server.config import Settings, get_settings

logger = logging.getLogger("mcp_server.providers.brightdata.client")


class BrightDataError(Exception):
    """Base exception for Bright Data API errors."""
    pass


class BrightDataClient:
    """Async client for interacting with Bright Data API."""

    DEFAULT_BASE_URL = "https://api.brightdata.com"
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        self._api_key = api_key or getattr(cfg, "brightdata_api_key", None)
        self.base_url = (base_url or getattr(cfg, "brightdata_base_url", None) or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._client = client

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is available."""
        return bool(self._api_key and self._api_key.strip())

    @property
    def headers(self) -> Dict[str, str]:
        """HTTP headers including Bearer authorization."""
        hdrs: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._api_key:
            hdrs["Authorization"] = f"Bearer {self._api_key.strip()}"
        return hdrs

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._client and not self._client.is_closed:
            return self._client
        return httpx.AsyncClient(timeout=self.timeout)

    async def get_status(self) -> Dict[str, Any]:
        """Check API key validity and account status."""
        if not self.is_configured:
            return {"status": "unconfigured", "can_make_requests": False, "message": "API key not set"}

        client = self._get_http_client()
        should_close = client != self._client
        try:
            resp = await client.get(f"{self.base_url}/status", headers=self.headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "code": resp.status_code, "text": resp.text[:200]}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            if should_close and not client.is_closed:
                await client.aclose()

    async def trigger_dataset(
        self,
        dataset_id: str,
        inputs: List[Dict[str, Any]],
        discover_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trigger an asynchronous dataset scrape collection."""
        if not self.is_configured:
            raise BrightDataError("Bright Data API key is not configured.")

        params = {"dataset_id": dataset_id, "include_errors": "true"}
        if discover_by:
            params["type"] = "discover_new"
            params["discover_by"] = discover_by

        client = self._get_http_client()
        should_close = client != self._client
        try:
            resp = await client.post(
                f"{self.base_url}/datasets/v3/trigger",
                headers=self.headers,
                params=params,
                json=inputs,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                raise BrightDataError(f"Bright Data trigger error ({resp.status_code}): {resp.text}")
            return resp.json()
        finally:
            if should_close and not client.is_closed:
                await client.aclose()
