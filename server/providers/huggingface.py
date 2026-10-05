"""Hugging Face dataset provider using official REST API."""

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



class HuggingFaceError(Exception):
    """Base exception for Hugging Face provider errors."""
    pass


class HuggingFaceNotFoundError(HuggingFaceError):
    """Raised when a dataset is not found (HTTP 404)."""
    pass


class HuggingFaceAuthenticationError(HuggingFaceError):
    """Raised when authentication fails or dataset is gated/private (HTTP 401/403)."""
    pass


class HuggingFaceRateLimitError(HuggingFaceError):
    """Raised when API rate limits are exceeded (HTTP 429)."""
    pass


class HuggingFaceTimeoutError(HuggingFaceError):
    """Raised when request times out."""
    pass


class HuggingFaceConnectionError(HuggingFaceError):
    """Raised when network connection fails."""
    pass


class HuggingFaceProvider(DatasetProvider):
    """Connector for Hugging Face datasets via official REST API."""

    DEFAULT_BASE_URL = "https://huggingface.co/api/datasets"
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
        self._token = token or cfg.hf_token
        self.base_url = (base_url or cfg.hf_api_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.hf_timeout
        self._client = client

    @property
    def platform_name(self) -> str:
        return "Hugging Face"

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
                operation_name="huggingface_request",
            )
        except httpx.TimeoutException as exc:
            raise HuggingFaceTimeoutError(f"Request to Hugging Face API timed out after {self.timeout}s") from exc
        except httpx.RequestError as exc:
            raise HuggingFaceConnectionError(f"Failed to connect to Hugging Face API: {exc}") from exc


    def _extract_license(self, tags: List[str], card_data: Dict[str, Any]) -> Optional[str]:
        # Check cardData first
        lic = card_data.get("license")
        if lic and isinstance(lic, str):
            return lic
        # Check tags e.g. license:mit, license:apache-2.0
        for tag in tags:
            if tag.startswith("license:"):
                return tag.split(":", 1)[1]
        return None

    def _extract_language(self, tags: List[str], card_data: Dict[str, Any]) -> Optional[str]:
        lang = card_data.get("language")
        if lang:
            if isinstance(lang, list) and lang:
                return str(lang[0])
            elif isinstance(lang, str):
                return lang
        for tag in tags:
            if tag.startswith("language:") or tag.startswith("lang:"):
                return tag.split(":", 1)[1]
        return None

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
        """Retrieve dataset metadata from official Hugging Face API."""
        clean_id = identifier.strip().strip("/")
        if not clean_id:
            raise ValueError("Dataset identifier cannot be empty.")

        async with async_timed_operation(logger, component="dataset", operation="resolve", provider="huggingface", identifier=clean_id):
            return await self._get_dataset_metadata_internal(clean_id)

    async def _get_dataset_metadata_internal(self, clean_id: str) -> DatasetMetadata:
        url = f"{self.base_url}/{clean_id}"
        response = await self._send_request(url)

        status_code = response.status_code
        if status_code == 404:
            raise HuggingFaceNotFoundError(f"Hugging Face dataset '{clean_id}' not found.")
        if status_code in (401, 403):
            raise HuggingFaceAuthenticationError(f"Access forbidden or requires authentication for '{clean_id}'.")
        if status_code == 429:
            raise HuggingFaceRateLimitError(f"Hugging Face API rate limit exceeded.")
        if status_code >= 500:
            raise HuggingFaceError(f"Hugging Face server error (HTTP {status_code}).")
        if status_code != 200:
            raise HuggingFaceError(f"Hugging Face API error (HTTP {status_code}): {response.text}")


        try:
            data = response.json()
        except Exception as exc:
            raise HuggingFaceError("Invalid JSON from Hugging Face API") from exc

        name = data.get("id") or clean_id
        description = data.get("description")
        card_data = data.get("cardData") or {}
        if not description and isinstance(card_data, dict):
            description = card_data.get("description")

        tags = data.get("tags") or []
        license_val = self._extract_license(tags, card_data)
        language_val = self._extract_language(tags, card_data)

        # Context string for rules
        text_context = f"{name} {description or ''} {' '.join(tags)}"
        data_type = self._classify_data_type(text_context)
        deid, anon, sens = self._detect_privacy(text_context)

        # Total size if siblings are returned
        size_bytes = None
        siblings = data.get("siblings")
        if isinstance(siblings, list):
            sizes = [s.get("size") for s in siblings if isinstance(s, dict) and isinstance(s.get("size"), int)]
            if sizes:
                size_bytes = sum(sizes)

        is_gated = bool(data.get("gated", False))
        is_private = bool(data.get("private", False))
        download_available = not is_private and not is_gated

        return DatasetMetadata(
            name=name,
            description=description,
            source_platform=self.platform_name,
            source_url=f"https://huggingface.co/datasets/{clean_id}",
            identifier=clean_id,
            data_type=data_type,
            format="parquet" if any("parquet" in t for t in tags) else None,
            language=language_val,
            license=license_val,
            created_at=data.get("createdAt"),
            updated_at=data.get("lastModified"),
            access_method="gated_access" if is_gated else "official_api",
            download_available=download_available,
            size_bytes=size_bytes,
            tags=tags,
            explicitly_deidentified=deid,
            explicitly_anonymized=anon,
            contains_sensitive_data_warning=sens,
            provenance="Hugging Face Hub API",
            notes="Metadata retrieved via official Hugging Face Hub REST API.",
        )
