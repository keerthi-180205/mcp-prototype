"""Comprehensive test suite for Phase 8 Productionization:
- Centralized configuration hardening and secret masking
- Secret safety and log scrubbing filter
- Structured logging with operational context and duration
- Resilience, exponential backoff, and retry policies on transient HTTP errors
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from server.config import Settings, get_settings, _mask_secret
from server.logging_config import (
    OperationContext,
    SecretScrubbingFilter,
    async_timed_operation,
    configure_logging,
    get_logger,
    timed_operation,
)
from server.resilience import (
    calculate_backoff_delay,
    is_status_retryable,
    retry_async_http,
    retry_async_operation,
    RETRYABLE_STATUS_CODES,
    NON_RETRYABLE_STATUS_CODES,
)


# ==============================================================================
# 1. Configuration Hardening & Secret Masking Tests
# ==============================================================================

def test_settings_defaults():
    """Verify Settings initializes with sensible production defaults."""
    settings = Settings(
        github_token=None,
        hf_token=None,
        kaggle_username=None,
        kaggle_key=None,
        zenodo_token=None,
        gemini_api_key=None,
    )
    assert settings.environment == "development"
    assert settings.log_level in ("INFO", "DEBUG", "WARNING", "ERROR")
    assert settings.github_api_base_url == "https://api.github.com"
    assert settings.github_timeout == 20.0
    assert settings.hf_api_base_url == "https://huggingface.co/api/datasets"
    assert settings.hf_timeout == 20.0
    assert settings.kaggle_api_base_url == "https://www.kaggle.com/api/v1/datasets/view"
    assert settings.kaggle_timeout == 20.0
    assert settings.zenodo_api_base_url == "https://zenodo.org/api/records"
    assert settings.zenodo_timeout == 20.0
    assert settings.gemini_model == "gemini-flash-lite-latest"
    assert settings.gemini_timeout == 90.0
    assert settings.max_retries == 3
    assert settings.retry_initial_delay == 0.5


def test_settings_secret_masking_in_repr():
    """Verify that credentials are NEVER exposed in plaintext when Settings is represented."""
    settings = Settings(
        github_token="ghp_SUPER_SECRET_GITHUB_TOKEN_12345",
        hf_token="hf_SUPER_SECRET_HUGGINGFACE_TOKEN_67890",
        kaggle_username="my_kaggle_user",
        kaggle_key="SUPER_SECRET_KAGGLE_API_KEY_ABCD",
        zenodo_token="SUPER_SECRET_ZENODO_TOKEN_EFGH",
        gemini_api_key="AIzaSy_SUPER_SECRET_GEMINI_API_KEY_IJKL",
    )
    rep = repr(settings)

    # Secret tokens must not be exposed in repr
    assert "SUPER_SECRET_GITHUB_TOKEN" not in rep
    assert "SUPER_SECRET_HUGGINGFACE_TOKEN" not in rep
    assert "SUPER_SECRET_KAGGLE_API_KEY" not in rep
    assert "SUPER_SECRET_ZENODO_TOKEN" not in rep
    assert "SUPER_SECRET_GEMINI_API_KEY" not in rep

    # Masked representations should be present
    assert "ghp...345" in rep
    assert "hf_...890" in rep
    assert "SUP...BCD" in rep


def test_mask_secret_helper():
    """Verify secret masking behavior for various lengths."""
    assert _mask_secret(None) == "<not_set>"
    assert _mask_secret("") == "<not_set>"
    assert _mask_secret("short") == "***"
    assert _mask_secret("123456") == "***"
    assert _mask_secret("abcdefghij") == "abc...hij"


def test_lazy_credential_validation():
    """Verify that Kaggle and Gemini configurations validate credentials on demand."""
    settings = Settings(
        kaggle_username=None,
        kaggle_key=None,
        gemini_api_key=None,
    )
    with pytest.raises(ValueError, match="Kaggle API authentication unavailable"):
        settings.validate_kaggle_credentials()

    with pytest.raises(ValueError, match="GEMINI_API_KEY environment variable is not configured"):
        settings.validate_gemini_credentials()

    # When configured, validation succeeds without error
    valid_settings = Settings(
        kaggle_username="user",
        kaggle_key="key",
        gemini_api_key="key",
    )
    valid_settings.validate_kaggle_credentials()
    valid_settings.validate_gemini_credentials()


# ==============================================================================
# 2. Secret Safety & Logging Filter Tests
# ==============================================================================

def test_secret_scrubbing_filter():
    """Verify that SecretScrubbingFilter redacts Bearer, Basic, and API key tokens."""
    filter_obj = SecretScrubbingFilter()

    # Raw string with sensitive header
    raw_message = "Calling API with Bearer ghp_VerySecretToken123456 and Basic dXNlcjpwYXNzMTIz"
    scrubbed = filter_obj.scrub_text(raw_message)

    assert "ghp_VerySecretToken123456" not in scrubbed
    assert "dXNlcjpwYXNzMTIz" not in scrubbed
    assert "Bearer [REDACTED]" in scrubbed
    assert "Basic [REDACTED]" in scrubbed


def test_secret_scrubbing_filter_record():
    """Verify filter modifies LogRecord messages in place."""
    filter_obj = SecretScrubbingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Executing request api_key=AIzaSySecretKey999999",
        args=(),
        exc_info=None,
    )
    filter_obj.filter(record)
    assert "AIzaSySecretKey999999" not in record.msg
    assert "[REDACTED]" in record.msg


# ==============================================================================
# 3. Structured Logging Context Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_async_timed_operation_success():
    """Verify async_timed_operation logs successful operation with duration."""
    test_logger = MagicMock()
    async with async_timed_operation(test_logger, component="test_comp", operation="test_op", initial="val") as op:
        await asyncio.sleep(0.01)
        op.set_status("completed")
        op.set_detail("extra", 42)

    test_logger.info.assert_called_once()
    call_args = test_logger.info.call_args[0]
    format_str = call_args[0]
    assert "%s.%s status=%s duration=%.2fs" in format_str
    assert call_args[1] == "test_comp"
    assert call_args[2] == "test_op"
    assert call_args[3] == "completed"


@pytest.mark.asyncio
async def test_async_timed_operation_failure():
    """Verify async_timed_operation logs failed operation and re-raises exception."""
    test_logger = MagicMock()
    with pytest.raises(ValueError, match="simulated error"):
        async with async_timed_operation(test_logger, component="test_comp", operation="test_op"):
            raise ValueError("simulated error")

    test_logger.error.assert_called_once()
    call_args = test_logger.error.call_args[0]
    format_str = call_args[0]
    assert "%s.%s status=failed duration=%.2fs" in format_str
    assert call_args[1] == "test_comp"
    assert call_args[2] == "test_op"


def test_sync_timed_operation():
    """Verify synchronous timed_operation works cleanly."""
    test_logger = MagicMock()
    with timed_operation(test_logger, component="sync_comp", operation="sync_op"):
        pass

    test_logger.info.assert_called_once()
    assert test_logger.info.call_args[0][1] == "sync_comp"


# ==============================================================================
# 4. Resilience, Retry, and Exponential Backoff Tests
# ==============================================================================

def test_backoff_delay_calculation():
    """Verify exponential backoff calculation and capping at max_delay."""
    # initial=0.5, factor=2.0, max=5.0
    assert calculate_backoff_delay(0, 0.5, 2.0, 5.0) == 0.5
    assert calculate_backoff_delay(1, 0.5, 2.0, 5.0) == 1.0
    assert calculate_backoff_delay(2, 0.5, 2.0, 5.0) == 2.0
    assert calculate_backoff_delay(3, 0.5, 2.0, 5.0) == 4.0
    # Capped at 5.0
    assert calculate_backoff_delay(4, 0.5, 2.0, 5.0) == 5.0
    assert calculate_backoff_delay(5, 0.5, 2.0, 5.0) == 5.0


def test_is_status_retryable():
    """Verify categorization of HTTP status codes for retries."""
    for code in (429, 500, 502, 503, 504):
        assert is_status_retryable(code) is True

    for code in (200, 201, 400, 401, 403, 404, 422):
        assert is_status_retryable(code) is False


@pytest.mark.asyncio
async def test_retry_async_http_success_on_retry():
    """Verify that a transient 503 followed by 200 succeeds after retrying."""
    resp_503 = httpx.Response(503, request=httpx.Request("GET", "https://api.test.com"))
    resp_200 = httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", "https://api.test.com"))

    mock_send = AsyncMock(side_effect=[resp_503, resp_200])

    response = await retry_async_http(
        mock_send,
        operation_name="test_call",
        max_retries=2,
        initial_delay=0.01,
        backoff_factor=1.0,
    )

    assert response.status_code == 200
    assert mock_send.call_count == 2


@pytest.mark.asyncio
async def test_retry_async_http_rate_limit_429():
    """Verify that an initial HTTP 429 retries and succeeds."""
    resp_429 = httpx.Response(429, request=httpx.Request("GET", "https://api.test.com"))
    resp_200 = httpx.Response(200, json={"items": []}, request=httpx.Request("GET", "https://api.test.com"))

    mock_send = AsyncMock(side_effect=[resp_429, resp_200])

    response = await retry_async_http(
        mock_send,
        operation_name="test_429",
        max_retries=2,
        initial_delay=0.01,
    )

    assert response.status_code == 200
    assert mock_send.call_count == 2


@pytest.mark.asyncio
async def test_retry_async_http_no_retry_on_client_errors():
    """Verify that HTTP 400, 401, 403, 404 fail immediately WITHOUT retrying."""
    for non_retryable_code in (400, 401, 403, 404, 422):
        resp_err = httpx.Response(non_retryable_code, request=httpx.Request("GET", "https://api.test.com"))
        mock_send = AsyncMock(return_value=resp_err)

        response = await retry_async_http(
            mock_send,
            operation_name=f"test_{non_retryable_code}",
            max_retries=3,
            initial_delay=0.01,
        )

        assert response.status_code == non_retryable_code
        # Must have been called exactly ONCE: zero retries performed!
        assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_retry_async_http_retries_on_network_error():
    """Verify that transient network errors (ConnectError) are retried."""
    req = httpx.Request("GET", "https://api.test.com")
    resp_200 = httpx.Response(200, json={"data": "recovered"}, request=req)

    mock_send = AsyncMock(side_effect=[httpx.ConnectError("Network unreachable"), resp_200])

    response = await retry_async_http(
        mock_send,
        operation_name="test_network_recovery",
        max_retries=2,
        initial_delay=0.01,
    )

    assert response.status_code == 200
    assert mock_send.call_count == 2


@pytest.mark.asyncio
async def test_retry_async_operation_generic():
    """Verify generic retry_async_operation with custom retryable exceptions."""
    class CustomTransientError(Exception):
        pass

    class CustomPermanentError(Exception):
        pass

    # Case 1: Recovers after transient error
    mock_op = AsyncMock(side_effect=[CustomTransientError("temporary"), "success"])
    result = await retry_async_operation(
        mock_op,
        retryable_exceptions=(CustomTransientError,),
        operation_name="custom_op",
        max_retries=2,
        initial_delay=0.01,
    )
    assert result == "success"
    assert mock_op.call_count == 2

    # Case 2: Permanent error fails immediately without retrying
    mock_permanent = AsyncMock(side_effect=CustomPermanentError("unauthorized"))
    with pytest.raises(CustomPermanentError):
        await retry_async_operation(
            mock_permanent,
            retryable_exceptions=(CustomTransientError,),
            operation_name="custom_perm_op",
            max_retries=2,
            initial_delay=0.01,
        )
    assert mock_permanent.call_count == 1


# ==============================================================================
# 5. Health and Readiness Tests
# ==============================================================================

def test_health_check_liveness():
    """Verify health_check returns standard liveness response without network calls."""
    from server.server import health_check
    result = health_check()
    assert result["status"] == "ok"
    assert result["service"] == "mmtf-client-discovery"
    assert result["message"] == "MCP server is running successfully"


def test_readiness_all_configured():
    """Verify readiness_check when all credentials (required + optional) are configured."""
    from server.server import readiness_check

    mock_settings = Settings(
        environment="production",
        github_token="ghp_test_12345",
        hf_token="hf_test_12345",
        kaggle_username="test_user",
        kaggle_key="test_key_12345",
        zenodo_token="zenodo_test_12345",
        gemini_api_key="AIzaSy_test_12345",
    )

    with patch("server.server.get_settings", return_value=mock_settings):
        res = readiness_check()

    assert res["status"] == "ready"
    assert res["environment"] == "production"
    providers = res["providers"]
    assert providers["github"] == {"status": "ready", "authentication": "configured"}
    assert providers["huggingface"] == {"status": "ready", "authentication": "configured"}
    assert providers["kaggle"] == {"status": "ready", "authentication": "configured"}
    assert providers["zenodo"] == {"status": "ready", "authentication": "configured"}
    assert providers["gemini"] == {"status": "ready", "authentication": "configured"}


def test_readiness_optional_unconfigured():
    """Verify readiness_check when optional credentials (GitHub, HF, Zenodo) are omitted."""
    from server.server import readiness_check

    mock_settings = Settings(
        environment="development",
        github_token=None,
        hf_token=None,
        kaggle_username="test_user",
        kaggle_key="test_key_12345",
        zenodo_token=None,
        gemini_api_key="AIzaSy_test_12345",
    )

    with patch("server.server.get_settings", return_value=mock_settings):
        res = readiness_check()

    assert res["status"] == "ready"
    assert res["environment"] == "development"
    providers = res["providers"]
    assert providers["github"] == {"status": "ready", "authentication": "optional_unconfigured"}
    assert providers["huggingface"] == {"status": "ready", "authentication": "optional_unconfigured"}
    assert providers["kaggle"] == {"status": "ready", "authentication": "configured"}
    assert providers["zenodo"] == {"status": "ready", "authentication": "optional_unconfigured"}
    assert providers["gemini"] == {"status": "ready", "authentication": "configured"}


def test_readiness_required_missing():
    """Verify readiness_check marks status not_ready when required configuration (Gemini) is missing."""
    from server.server import readiness_check

    mock_settings = Settings(
        environment="development",
        github_token=None,
        hf_token=None,
        kaggle_username=None,
        kaggle_key=None,
        zenodo_token=None,
        gemini_api_key=None,
    )

    with patch("server.server.get_settings", return_value=mock_settings):
        res = readiness_check()

    assert res["status"] == "not_ready"
    assert res["environment"] == "development"
    providers = res["providers"]
    assert providers["kaggle"] == {"status": "not_ready", "authentication": "missing"}
    assert providers["gemini"] == {"status": "not_ready", "authentication": "missing"}

