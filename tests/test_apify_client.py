"""Unit tests for Apify API client."""

from unittest.mock import AsyncMock, patch
import httpx
import pytest

from server.config import Settings
from server.providers.apify.client import (
    ApifyActorError,
    ApifyAuthenticationError,
    ApifyClient,
    ApifyConnectionError,
    ApifyError,
    ApifyRateLimitError,
    ApifyTimeoutError,
)


@pytest.fixture
def mock_settings():
    return Settings(
        apify_api_token="apify_api_test_secret_token_12345",
        apify_api_base_url="https://api.apify.com/v2",
        apify_timeout=30.0,
    )


def test_apify_settings_token_loaded(mock_settings):
    """Verify APIFY_API_TOKEN is loaded correctly and masked in repr."""
    assert mock_settings.apify_api_token == "apify_api_test_secret_token_12345"
    repr_str = repr(mock_settings)
    assert "apify_api_test_secret_token_12345" not in repr_str
    assert "api...345" in repr_str


def test_apify_settings_validation_missing_token():
    """Verify validation raises ValueError when APIFY_API_TOKEN is missing."""
    empty_settings = Settings(apify_api_token=None)
    with pytest.raises(ValueError, match="APIFY_API_TOKEN environment variable is not configured"):
        empty_settings.validate_apify_credentials()


def test_apify_client_headers(mock_settings):
    """Verify ApifyClient sets Bearer authorization header."""
    client = ApifyClient(settings=mock_settings)
    headers = client.headers
    assert headers["Authorization"] == "Bearer apify_api_test_secret_token_12345"
    assert headers["Content-Type"] == "application/json"


def test_apify_client_sanitize_actor_id(mock_settings):
    """Verify actor ID with slash is converted to tilde format for Apify REST API."""
    client = ApifyClient(settings=mock_settings)
    assert client._sanitize_actor_id("apify/instagram-scraper") == "apify~instagram-scraper"
    assert client._sanitize_actor_id("apify~instagram-scraper") == "apify~instagram-scraper"


@pytest.mark.asyncio
async def test_run_actor_missing_token():
    """Verify error when running without token."""
    client = ApifyClient(token=None, settings=Settings(apify_api_token=None))
    with pytest.raises(ApifyAuthenticationError, match="APIFY_API_TOKEN is not configured"):
        await client.run_actor_sync_get_dataset("apify/instagram-scraper", {})


@pytest.mark.asyncio
async def test_run_actor_success(mock_settings):
    """Verify successful run returns dataset items list."""
    mock_items = [
        {"id": "post1", "caption": "Mental health awareness", "likesCount": 42},
        {"id": "post2", "caption": "Self care tips", "likesCount": 100},
    ]

    mock_resp = httpx.Response(
        status_code=200,
        json=mock_items,
        request=httpx.Request("POST", "https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items"),
    )

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)

    client = ApifyClient(settings=mock_settings, client=mock_http_client)
    items = await client.run_actor_sync_get_dataset(
        actor_id="apify/instagram-scraper",
        run_input={"search": "mental health"},
    )

    assert items == mock_items
    mock_http_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_run_actor_auth_error_401(mock_settings):
    """Verify HTTP 401 raises ApifyAuthenticationError without leaking token."""
    mock_resp = httpx.Response(
        status_code=401,
        json={"error": {"type": "user-or-token-not-found", "message": "Invalid token"}},
        request=httpx.Request("POST", "https://api.apify.com/v2"),
    )

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)

    client = ApifyClient(settings=mock_settings, client=mock_http_client)
    with pytest.raises(ApifyAuthenticationError, match="Apify authentication failed"):
        await client.run_actor_sync_get_dataset("apify/instagram-scraper", {})


@pytest.mark.asyncio
async def test_run_actor_rate_limit_429(mock_settings):
    """Verify HTTP 429 raises ApifyRateLimitError when retries exhaust."""
    mock_resp = httpx.Response(
        status_code=429,
        json={"error": {"type": "rate-limit-exceeded", "message": "Too many requests"}},
        request=httpx.Request("POST", "https://api.apify.com/v2"),
    )

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)

    # Use settings with 0 retries to test fast
    fast_settings = Settings(
        apify_api_token="test_token",
        max_retries=0,
    )
    client = ApifyClient(settings=fast_settings, client=mock_http_client)
    with pytest.raises(ApifyRateLimitError, match="rate limit"):
        await client.run_actor_sync_get_dataset("apify/instagram-scraper", {})


@pytest.mark.asyncio
async def test_run_actor_timeout_408(mock_settings):
    """Verify HTTP 408 raises ApifyTimeoutError."""
    mock_resp = httpx.Response(
        status_code=408,
        json={"error": {"type": "run-timeout-exceeded", "message": "Timeout exceeded"}},
        request=httpx.Request("POST", "https://api.apify.com/v2"),
    )

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)

    fast_settings = Settings(apify_api_token="test_token", max_retries=0)
    client = ApifyClient(settings=fast_settings, client=mock_http_client)
    with pytest.raises(ApifyTimeoutError, match="timed out"):
        await client.run_actor_sync_get_dataset("apify/instagram-scraper", {})


@pytest.mark.asyncio
async def test_run_actor_not_found_404(mock_settings):
    """Verify HTTP 404 raises ApifyActorError."""
    mock_resp = httpx.Response(
        status_code=404,
        json={"error": {"type": "act-not-found", "message": "Actor does not exist"}},
        request=httpx.Request("POST", "https://api.apify.com/v2"),
    )

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)

    client = ApifyClient(settings=mock_settings, client=mock_http_client)
    with pytest.raises(ApifyActorError, match="not found"):
        await client.run_actor_sync_get_dataset("nonexistent/actor", {})
