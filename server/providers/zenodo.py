"""Zenodo dataset provider using official REST API."""

import os
import re
from typing import Any, Dict, List, Optional
import httpx

from server.config import Settings, get_settings
from server.logging_config import async_timed_operation, get_logger
from server.models import DatasetMetadata
from server.providers.base import DatasetProvider
from server.resilience import retry_async_http

logger = get_logger(__name__)



class ZenodoError(Exception):
    """Base exception for Zenodo provider errors."""
    pass


class ZenodoNotFoundError(ZenodoError):
    """Raised when a Zenodo record is not found (HTTP 404)."""
    pass


class ZenodoAuthenticationError(ZenodoError):
    """Raised when authentication fails (HTTP 401/403)."""
    pass


class ZenodoRateLimitError(ZenodoError):
    """Raised when Zenodo API rate limits are exceeded (HTTP 429)."""
    pass


class ZenodoTimeoutError(ZenodoError):
    """Raised when request times out."""
    pass


class ZenodoConnectionError(ZenodoError):
    """Raised when network connection fails."""
    pass


class ZenodoProvider(DatasetProvider):
    """Connector for Zenodo records via official REST API.

    Public metadata lookup works without requiring authentication.
    Does NOT scrape Zenodo web pages.
    """

    DEFAULT_BASE_URL = "https://zenodo.org/api/records"
    DEFAULT_TIMEOUT = 20.0
    USER_AGENT = "MMTF-MCP-Client-Discovery/0.1"

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        self._token = token or cfg.zenodo_token
        self.base_url = (base_url or cfg.zenodo_api_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.zenodo_timeout
        self._client = client

    @property
    def platform_name(self) -> str:
        return "Zenodo"

    @property
    def headers(self) -> Dict[str, str]:
        hdrs = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        if self._token:
            hdrs["Authorization"] = f"Bearer {self._token}"
        return hdrs

    async def _send_request(self, url: str) -> httpx.Response:
        async def _make_call() -> httpx.Response:
            if self._client:
                return await self._client.get(url, headers=self.headers)
            else:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    return await client.get(url, headers=self.headers)

        try:
            return await retry_async_http(
                _make_call,
                operation_name="zenodo_request",
            )
        except httpx.TimeoutException as exc:
            raise ZenodoTimeoutError(f"Request to Zenodo API timed out after {self.timeout}s") from exc
        except httpx.RequestError as exc:
            raise ZenodoConnectionError(f"Failed to connect to Zenodo API: {exc}") from exc

    def _classify_data_type(self, text_context: str) -> str:
        if re.search(r"\b(therapy|conversation|dialogue|chat|counseling)\b", text_context, re.I):
            return "conversation"
        if re.search(r"\b(phq|gad|survey|questionnaire|assessment)\b", text_context, re.I):
            return "mental_health_assessment"
        if re.search(r"\b(emotion|sentiment|affect|mood)\b", text_context, re.I):
            return "emotion"
        if re.search(r"\b(text|corpus|tweet|reddit|social media|post)\b", text_context, re.I):
            return "text"
        if re.search(r"\b(audio|speech|video|multimodal)\b", text_context, re.I):
            return "multimodal"
        return "research_data"

    def _detect_privacy(self, text: str) -> tuple[Optional[bool], Optional[bool], Optional[bool]]:
        anon = True if re.search(r"\b(anonymi[zs]ed|anonymi[zs]ation)\b", text, re.I) else None
        deid = True if re.search(r"\b(de-identified|deidentified)\b", text, re.I) else None
        sens = True if re.search(r"\b(sensitive personal|distress warning|trigger warning|suicid)\b", text, re.I) else None
        return deid, anon, sens

    async def get_dataset_metadata(self, identifier: str) -> DatasetMetadata:
        """Retrieve dataset metadata from official Zenodo REST API by record ID."""
        clean_id = identifier.strip().strip("/")
        # Extract record ID if full DOI passed (e.g. 10.5281/zenodo.123456 -> 123456)
        if "zenodo." in clean_id:
            clean_id = clean_id.split("zenodo.")[-1]

        if not clean_id or not clean_id.isdigit():
            raise ValueError(f"Invalid Zenodo record ID: '{identifier}'. Expected numeric ID.")

        async with async_timed_operation(logger, component="dataset", operation="resolve", provider="zenodo", identifier=clean_id):
            return await self._get_dataset_metadata_internal(clean_id)

    async def _get_dataset_metadata_internal(self, clean_id: str) -> DatasetMetadata:
        url = f"{self.base_url}/{clean_id}"
        response = await self._send_request(url)


        status_code = response.status_code
        if status_code == 404:
            raise ZenodoNotFoundError(f"Zenodo record '{clean_id}' not found.")
        if status_code in (401, 403):
            raise ZenodoAuthenticationError(f"Access forbidden to Zenodo record '{clean_id}'.")
        if status_code == 429:
            raise ZenodoRateLimitError("Zenodo API rate limit exceeded.")
        if status_code >= 500:
            raise ZenodoError(f"Zenodo server error (HTTP {status_code}).")
        if status_code != 200:
            raise ZenodoError(f"Zenodo API returned HTTP {status_code}: {response.text}")

        try:
            data = response.json()
        except Exception as exc:
            raise ZenodoError("Invalid JSON response from Zenodo API") from exc

        metadata = data.get("metadata") or {}
        title = metadata.get("title") or f"Zenodo Record {clean_id}"
        description = metadata.get("description")

        # License
        license_info = metadata.get("license")
        license_str = None
        if isinstance(license_info, dict):
            license_str = license_info.get("id") or license_info.get("title")
        elif isinstance(license_info, str):
            license_str = license_info

        # Files & size
        files = data.get("files") or []
        size_bytes = sum(f.get("size", 0) for f in files if isinstance(f, dict)) if files else None
        download_available = len(files) > 0

        # Creators
        creators = metadata.get("creators") or []
        creator_names = [c.get("name") for c in creators if isinstance(c, dict) and "name" in c]
        provenance = f"Creators: {', '.join(creator_names)}" if creator_names else "Zenodo Community"

        # Keywords / tags
        keywords = metadata.get("keywords") or []

        text_context = f"{title} {description or ''} {' '.join(keywords)}"
        data_type = self._classify_data_type(text_context)
        deid, anon, sens = self._detect_privacy(text_context)

        return DatasetMetadata(
            name=title,
            description=description,
            source_platform=self.platform_name,
            source_url=f"https://zenodo.org/records/{clean_id}",
            identifier=clean_id,
            data_type=data_type,
            license=license_str,
            created_at=data.get("created"),
            updated_at=data.get("modified"),
            access_method="official_api",
            download_available=download_available,
            size_bytes=size_bytes,
            tags=keywords,
            explicitly_deidentified=deid,
            explicitly_anonymized=anon,
            contains_sensitive_data_warning=sens,
            provenance=provenance,
            notes=f"DOI: {metadata.get('doi') or data.get('doi') or 'N/A'}",
        )
