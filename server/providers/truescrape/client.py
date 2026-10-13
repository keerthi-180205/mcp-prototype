"""TrueScrape API client for high-performance social media scraping.

Isolates all raw HTTP communication with the TrueScrape REST API (https://api.truescrape.com).
Authenticates via the 'x-api-key' header, handles unified cross-platform endpoints,
provides retry resilience, and normalizes responses.
"""

from typing import Any, Dict, Optional
import httpx

from server.config import Settings, get_settings
from server.logging_config import async_timed_operation, get_logger
from server.resilience import retry_async_http

logger = get_logger(__name__)


class TrueScrapeError(Exception):
    """Base exception for TrueScrape client and API errors."""
    pass


class TrueScrapeAuthenticationError(TrueScrapeError):
    """Raised when TrueScrape authentication fails or API key is missing/invalid (HTTP 401/403)."""
    pass


class TrueScrapeRateLimitError(TrueScrapeError):
    """Raised when TrueScrape API rate limits or quota are exceeded (HTTP 429)."""
    pass


class TrueScrapeTimeoutError(TrueScrapeError):
    """Raised when TrueScrape request times out."""
    pass


class TrueScrapeConnectionError(TrueScrapeError):
    """Raised when network connection to TrueScrape fails."""
    pass


class TrueScrapeClient:
    """Async client for interacting with TrueScrape REST API."""

    DEFAULT_BASE_URL = "https://api.truescrape.com"
    DEFAULT_TIMEOUT = 30.0
    USER_AGENT = "MMTF-MCP-TrueScrape-Client/1.0"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        self._api_key = api_key or cfg.truescrape_api_key
        self.base_url = (base_url or cfg.truescrape_api_base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.truescrape_timeout
        self._client = client

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is available."""
        return bool(self._api_key and self._api_key.strip())

    @property
    def headers(self) -> Dict[str, str]:
        """HTTP headers including x-api-key authentication."""
        hdrs: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        if self._api_key:
            hdrs["x-api-key"] = self._api_key.strip()
        return hdrs

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return an active httpx client or create a transient one."""
        if self._client is not None and not self._client.is_closed:
            return self._client
        return httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform a GET request to a TrueScrape endpoint.

        Args:
            endpoint: API path (e.g. '/v1/instagram/popular-search' or '/v1/instagram/post-comments')
            params: Query parameters.

        Returns:
            Decoded JSON payload (dict).

        Raises:
            TrueScrapeAuthenticationError: On HTTP 401/403.
            TrueScrapeRateLimitError: On HTTP 429.
            TrueScrapeTimeoutError: On request timeout.
            TrueScrapeConnectionError: On network errors.
            TrueScrapeError: On HTTP 4xx/5xx or unexpected failures.
        """
        if not self.is_configured:
            raise TrueScrapeAuthenticationError(
                "TrueScrape API key is not configured. Set TRUESCRAPE_API_KEY in your environment or .env file."
            )

        clean_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.base_url}{clean_path}"

        # Clean None values from params
        query_params = {k: v for k, v in (params or {}).items() if v is not None}

        owns_client = self._client is None or self._client.is_closed
        http_client = self._get_http_client()

        masked_key = f"{self._api_key[:8]}...{self._api_key[-4:]}" if self._api_key and len(self._api_key) > 12 else "***"
        logger.debug("[TRUESCRAPE] GET %s params=%s key=%s", url, query_params, masked_key)

        try:
            async with async_timed_operation(logger, "truescrape_client", f"get_{clean_path.strip('/').replace('/', '_')}"):
                response = await retry_async_http(
                    lambda: http_client.get(
                        url,
                        headers=self.headers,
                        params=query_params,
                    )
                )

            if response.status_code in (401, 403):
                raise TrueScrapeAuthenticationError(
                    f"TrueScrape authentication failed (HTTP {response.status_code}): {response.text}"
                )
            elif response.status_code == 429:
                raise TrueScrapeRateLimitError(
                    f"TrueScrape rate limit exceeded (HTTP 429): {response.text}"
                )
            elif response.status_code >= 400:
                raise TrueScrapeError(
                    f"TrueScrape API error (HTTP {response.status_code}): {response.text}"
                )

            return response.json()

        except httpx.TimeoutException as exc:
            logger.error("[TRUESCRAPE] Request timed out for %s: %s", url, exc)
            raise TrueScrapeTimeoutError(f"TrueScrape request timed out: {exc}") from exc
        except httpx.NetworkError as exc:
            logger.error("[TRUESCRAPE] Connection error for %s: %s", url, exc)
            raise TrueScrapeConnectionError(f"TrueScrape connection error: {exc}") from exc
        except (TrueScrapeError, TrueScrapeAuthenticationError, TrueScrapeRateLimitError):
            raise
        except Exception as exc:
            logger.error("[TRUESCRAPE] Unexpected error calling %s: %s", url, exc, exc_info=True)
            raise TrueScrapeError(f"Unexpected TrueScrape error: {exc}") from exc
        finally:
            if owns_client and not http_client.is_closed:
                await http_client.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client session if owned."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
