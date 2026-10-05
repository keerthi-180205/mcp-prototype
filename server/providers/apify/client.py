"""Apify API client for executing Actors and retrieving dataset items.

Isolates all raw HTTP communication with the Apify REST API (v2).
Provides resilience via exponential backoff retries on transient errors,
strict masking of credentials, and clear exception mapping.
"""

from typing import Any, Dict, List, Optional
import httpx

from server.config import Settings, get_settings
from server.logging_config import async_timed_operation, get_logger
from server.resilience import retry_async_http

logger = get_logger(__name__)


class ApifyError(Exception):
    """Base exception for Apify client and API errors."""
    pass


class ApifyAuthenticationError(ApifyError):
    """Raised when Apify authentication fails or token is missing/invalid (HTTP 401/402/403)."""
    pass


class ApifyActorError(ApifyError):
    """Raised when an Apify Actor fails or is not found (HTTP 400/404)."""
    pass


class ApifyRateLimitError(ApifyError):
    """Raised when Apify API rate limits are exceeded (HTTP 429)."""
    pass


class ApifyTimeoutError(ApifyError):
    """Raised when an Apify request or Actor execution times out (HTTP 408)."""
    pass


class ApifyConnectionError(ApifyError):
    """Raised when network connection to Apify API fails."""
    pass


class ApifyEmptyDatasetError(ApifyError):
    """Raised when an Apify Actor returns an unexpectedly empty dataset."""
    pass


class ApifyClient:
    """Async client for interacting with Apify REST API v2."""

    DEFAULT_BASE_URL = "https://api.apify.com/v2"
    DEFAULT_TIMEOUT = 120.0
    USER_AGENT = "MMTF-MCP-Instagram-Discovery/0.1"

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        self._token = token or cfg.apify_api_token
        self.base_url = (base_url or cfg.apify_api_base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.apify_timeout
        self._client = client

    @property
    def headers(self) -> Dict[str, str]:
        """HTTP headers including Bearer token authentication."""
        hdrs = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        if self._token:
            hdrs["Authorization"] = f"Bearer {self._token}"
        return hdrs

    def _sanitize_actor_id(self, actor_id: str) -> str:
        """Convert 'username/actor-name' format to Apify REST URL format 'username~actor-name'."""
        clean_id = actor_id.strip()
        if "/" in clean_id:
            return clean_id.replace("/", "~")
        return clean_id

    def _extract_error_message(self, response: httpx.Response) -> str:
        """Safely extract error message from Apify response without exposing secrets."""
        try:
            payload = response.json()
            if isinstance(payload, dict) and "error" in payload:
                err = payload["error"]
                if isinstance(err, dict):
                    return err.get("message", str(err))
                return str(err)
            return response.text[:200]
        except Exception:
            return f"HTTP {response.status_code}"

    async def run_actor_sync_get_dataset(
        self,
        actor_id: str,
        run_input: Dict[str, Any],
        timeout_secs: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Run an Apify Actor synchronously and return resulting dataset items.

        Calls the Apify POST /v2/acts/{actorId}/run-sync-get-dataset-items endpoint.

        Args:
            actor_id: Full Actor identifier (e.g. 'apify/instagram-scraper' or 'apify~instagram-scraper').
            run_input: Dictionary payload passed as input to the Actor.
            timeout_secs: Max execution timeout in seconds. Defaults to client timeout.

        Returns:
            List of dataset items (dictionaries).

        Raises:
            ApifyAuthenticationError: Missing or invalid credentials.
            ApifyRateLimitError: Rate limit exceeded (HTTP 429).
            ApifyTimeoutError: Execution timed out (HTTP 408).
            ApifyActorError: Actor not found (404) or bad input (400).
            ApifyConnectionError: Network connectivity failure.
            ApifyError: Generic provider error.
        """
        if not self._token:
            raise ApifyAuthenticationError(
                "APIFY_API_TOKEN is not configured. Please set the APIFY_API_TOKEN environment variable."
            )

        sanitized_actor = self._sanitize_actor_id(actor_id)
        effective_timeout = timeout_secs if timeout_secs is not None else self.timeout
        # Apify run-sync-get-dataset-items endpoint supports timeout query param (max 300s)
        api_wait_timeout = min(int(effective_timeout), 300)
        url = f"{self.base_url}/acts/{sanitized_actor}/run-sync-get-dataset-items"
        params = {
            "timeout": api_wait_timeout,
            "format": "json",
            "clean": 1,
        }

        async def _make_call() -> httpx.Response:
            if self._client:
                return await self._client.post(
                    url,
                    headers=self.headers,
                    params=params,
                    json=run_input,
                    timeout=effective_timeout + 10.0,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=effective_timeout + 10.0,
                    follow_redirects=True,
                ) as client:
                    return await client.post(
                        url,
                        headers=self.headers,
                        params=params,
                        json=run_input,
                    )

        async with async_timed_operation(logger, component="apify_client", operation=f"run_actor_{sanitized_actor}"):
            try:
                response = await retry_async_http(
                    _make_call,
                    operation_name=f"apify_actor_{sanitized_actor}",
                )
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                raise ApifyConnectionError(f"Failed to connect to Apify API: {exc}") from exc
            except (httpx.TimeoutException, httpx.ReadTimeout) as exc:
                raise ApifyTimeoutError(
                    f"Apify Actor '{actor_id}' timed out after {effective_timeout:.0f}s: {exc}"
                ) from exc
            except Exception as exc:
                if isinstance(exc, (ApifyError, ApifyAuthenticationError)):
                    raise
                raise ApifyConnectionError(f"Unexpected error connecting to Apify: {exc}") from exc

            # Handle HTTP status codes
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        # Some actors return a dict with items or single object
                        if "items" in data and isinstance(data["items"], list):
                            return data["items"]
                        return [data]
                    return []
                except Exception as exc:
                    raise ApifyError(f"Failed to parse Apify response JSON: {exc}") from exc

            err_msg = self._extract_error_message(response)

            if response.status_code == 401:
                raise ApifyAuthenticationError(f"Apify authentication failed: {err_msg}")
            elif response.status_code == 402:
                raise ApifyAuthenticationError(f"Apify payment required or quota exhausted: {err_msg}")
            elif response.status_code == 403:
                raise ApifyAuthenticationError(f"Apify permission denied for actor '{actor_id}': {err_msg}")
            elif response.status_code == 404:
                raise ApifyActorError(f"Apify Actor '{actor_id}' was not found: {err_msg}")
            elif response.status_code == 408:
                raise ApifyTimeoutError(f"Apify Actor execution timed out: {err_msg}")
            elif response.status_code == 429:
                raise ApifyRateLimitError(f"Apify rate limit exceeded: {err_msg}")
            elif response.status_code == 400:
                raise ApifyActorError(f"Apify invalid input: {err_msg}")
            else:
                raise ApifyError(f"Apify API returned HTTP {response.status_code}: {err_msg}")
