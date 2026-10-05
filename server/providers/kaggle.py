"""Kaggle dataset provider using official REST API."""

import base64
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



class KaggleError(Exception):
    """Base exception for Kaggle provider errors."""
    pass


class KaggleNotFoundError(KaggleError):
    """Raised when a dataset is not found (HTTP 404)."""
    pass


class KaggleAuthenticationError(KaggleError):
    """Raised when Kaggle credentials are missing, invalid, or access is unauthorized."""
    pass


class KaggleRateLimitError(KaggleError):
    """Raised when Kaggle API rate limits are exceeded (HTTP 429)."""
    pass


class KaggleTimeoutError(KaggleError):
    """Raised when request times out."""
    pass


class KaggleConnectionError(KaggleError):
    """Raised when network connection fails."""
    pass


class KaggleProvider(DatasetProvider):
    """Connector for Kaggle datasets via official REST API.

    Requires official Kaggle API credentials (KAGGLE_USERNAME and KAGGLE_KEY).
    Does NOT scrape Kaggle web pages.
    """

    DEFAULT_BASE_URL = "https://www.kaggle.com/api/v1/datasets/view"
    DEFAULT_TIMEOUT = 20.0
    USER_AGENT = "MMTF-MCP-Client-Discovery/0.1"

    _DEFAULT_SENTINEL = object()

    def __init__(
        self,
        username: Any = _DEFAULT_SENTINEL,
        key: Any = _DEFAULT_SENTINEL,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        if username is self._DEFAULT_SENTINEL:
            self._username = cfg.kaggle_username
        else:
            self._username = username or None

        if key is self._DEFAULT_SENTINEL:
            self._key = cfg.kaggle_key
        else:
            self._key = key or None

        self.base_url = (base_url or cfg.kaggle_api_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.kaggle_timeout
        self._client = client

    @property
    def platform_name(self) -> str:
        return "Kaggle"

    @property
    def is_authenticated(self) -> bool:
        return bool(self._username and self._key)

    @property
    def headers(self) -> Dict[str, str]:
        hdrs = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        if self.is_authenticated:
            auth_str = f"{self._username}:{self._key}"
            encoded = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            hdrs["Authorization"] = f"Basic {encoded}"
        return hdrs

    async def _send_request(self, url: str) -> httpx.Response:
        async def _make_call() -> httpx.Response:
            if self._client:
                return await self._client.get(url, headers=self.headers)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    return await client.get(url, headers=self.headers)

        try:
            return await retry_async_http(
                _make_call,
                operation_name="kaggle_request",
            )
        except httpx.TimeoutException as exc:
            raise KaggleTimeoutError(f"Request to Kaggle API timed out after {self.timeout}s") from exc
        except httpx.RequestError as exc:
            raise KaggleConnectionError(f"Failed to connect to Kaggle API: {exc}") from exc

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
        """Retrieve dataset metadata from official Kaggle API."""
        if not self.is_authenticated:
            raise KaggleAuthenticationError(
                "Kaggle API authentication unavailable. Please set KAGGLE_USERNAME and KAGGLE_KEY environment variables."
            )

        clean_id = identifier.strip().strip("/")
        if not clean_id or "/" not in clean_id:
            raise ValueError(f"Invalid Kaggle dataset identifier: '{identifier}'. Expected 'owner/dataset-name'.")

        async with async_timed_operation(logger, component="dataset", operation="resolve", provider="kaggle", identifier=clean_id):
            return await self._get_dataset_metadata_internal(clean_id)

    async def _get_dataset_metadata_internal(self, clean_id: str) -> DatasetMetadata:
        url = f"{self.base_url}/{clean_id}"
        response = await self._send_request(url)


        status_code = response.status_code
        if status_code == 404:
            raise KaggleNotFoundError(f"Kaggle dataset '{clean_id}' not found.")
        if status_code in (401, 403):
            raise KaggleAuthenticationError(f"Kaggle authentication failed or access forbidden for '{clean_id}'.")
        if status_code == 429:
            raise KaggleRateLimitError("Kaggle API rate limit exceeded.")
        if status_code >= 500:
            raise KaggleError(f"Kaggle server error (HTTP {status_code}).")
        if status_code != 200:
            raise KaggleError(f"Kaggle API returned HTTP {status_code}: {response.text}")

        try:
            data = response.json()
        except Exception as exc:
            raise KaggleError("Invalid JSON response from Kaggle API") from exc

        title = data.get("title") or clean_id
        description = data.get("description")
        license_name = data.get("licenseName")
        size_bytes = data.get("totalBytes")
        updated_at = data.get("lastUpdated")

        keywords = data.get("keywords") or []
        tags: List[str] = []
        if isinstance(keywords, list):
            for k in keywords:
                if isinstance(k, dict) and "name" in k:
                    tags.append(k["name"])
                elif isinstance(k, str):
                    tags.append(k)

        text_context = f"{title} {description or ''} {' '.join(tags)}"
        data_type = self._classify_data_type(text_context)
        deid, anon, sens = self._detect_privacy(text_context)

        return DatasetMetadata(
            name=title,
            description=description,
            source_platform=self.platform_name,
            source_url=f"https://www.kaggle.com/datasets/{clean_id}",
            identifier=clean_id,
            data_type=data_type,
            license=license_name,
            updated_at=updated_at,
            access_method="official_api",
            download_available=True,
            size_bytes=size_bytes,
            tags=tags,
            explicitly_deidentified=deid,
            explicitly_anonymized=anon,
            contains_sensitive_data_warning=sens,
            provenance="Kaggle REST API",
            notes="Metadata retrieved via official Kaggle REST API.",
        )
