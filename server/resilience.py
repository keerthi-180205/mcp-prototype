"""Resilience module implementing exponential backoff retries for transient failures.

Provides controlled retry mechanisms for transient HTTP status codes (429, 500, 502, 503, 504)
and network connection resets while immediately failing fast on permanent client/auth errors
(400, 401, 403, 404, 422).
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Set, TypeVar
import httpx

from server.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes that represent transient, retryable failures
RETRYABLE_STATUS_CODES: Set[int] = {429, 500, 502, 503, 504}

# HTTP status codes that represent deterministic client or authorization errors (never retry)
NON_RETRYABLE_STATUS_CODES: Set[int] = {400, 401, 403, 404, 422}

# Exceptions that represent transient network connectivity issues
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


def is_status_retryable(status_code: int) -> bool:
    """Return True if the HTTP status code is a transient, retryable failure."""
    return status_code in RETRYABLE_STATUS_CODES


def calculate_backoff_delay(
    attempt: int,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    max_delay: float = 5.0,
) -> float:
    """Calculate exponential backoff delay for the given retry attempt (0-indexed)."""
    delay = initial_delay * (backoff_factor ** attempt)
    return min(delay, max_delay)


async def retry_async_http(
    send_fn: Callable[[], Awaitable[httpx.Response]],
    operation_name: str = "http_request",
    max_retries: Optional[int] = None,
    initial_delay: Optional[float] = None,
    backoff_factor: Optional[float] = None,
    max_delay: Optional[float] = None,
) -> httpx.Response:
    """Execute an HTTP request coroutine with exponential backoff retries on transient errors.

    Retries on:
    - HTTP 429 (Rate limited)
    - HTTP 500, 502, 503, 504 (Server errors / Gateway issues)
    - Network connection / timeout exceptions

    Never retries:
    - HTTP 400, 401, 403, 404, 422
    """
    settings = get_settings()
    retries = max_retries if max_retries is not None else settings.max_retries
    init_delay = initial_delay if initial_delay is not None else settings.retry_initial_delay
    factor = backoff_factor if backoff_factor is not None else settings.retry_backoff_factor
    m_delay = max_delay if max_delay is not None else settings.retry_max_delay

    last_exc: Optional[Exception] = None
    response: Optional[httpx.Response] = None

    for attempt in range(retries + 1):
        try:
            response = await send_fn()
            # If status code is not transiently failed, return immediately
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response

            # If it's a retryable status code and we have retries left:
            if attempt < retries:
                delay = calculate_backoff_delay(attempt, init_delay, factor, m_delay)
                logger.warning(
                    "[RETRY] %s returned transient HTTP %d. Retrying in %.2fs (attempt %d/%d)...",
                    operation_name,
                    response.status_code,
                    delay,
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(delay)
                continue
            else:
                # Retries exhausted, return response for normal domain error handling
                return response

        except RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < retries:
                delay = calculate_backoff_delay(attempt, init_delay, factor, m_delay)
                logger.warning(
                    "[RETRY] %s transient network error (%s: %s). Retrying in %.2fs (attempt %d/%d)...",
                    operation_name,
                    type(exc).__name__,
                    exc,
                    delay,
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(delay)
                continue
            else:
                raise last_exc
        except Exception:
            # Non-retryable unexpected exception (e.g. ValueError, custom domain error)
            raise

    # Fallback return if loop ends
    if response is not None:
        return response
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{operation_name} failed without a response or exception.")


async def retry_async_operation(
    operation_fn: Callable[[], Awaitable[T]],
    retryable_exceptions: tuple,
    operation_name: str = "operation",
    max_retries: Optional[int] = None,
    initial_delay: Optional[float] = None,
    backoff_factor: Optional[float] = None,
    max_delay: Optional[float] = None,
) -> T:
    """Execute any async function with exponential backoff on specified transient exceptions."""
    settings = get_settings()
    retries = max_retries if max_retries is not None else settings.max_retries
    init_delay = initial_delay if initial_delay is not None else settings.retry_initial_delay
    factor = backoff_factor if backoff_factor is not None else settings.retry_backoff_factor
    m_delay = max_delay if max_delay is not None else settings.retry_max_delay

    last_exc: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            return await operation_fn()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt < retries:
                delay = calculate_backoff_delay(attempt, init_delay, factor, m_delay)
                logger.warning(
                    "[RETRY] %s encountered %s: %s. Retrying in %.2fs (attempt %d/%d)...",
                    operation_name,
                    type(exc).__name__,
                    exc,
                    delay,
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(delay)
                continue
            else:
                raise last_exc

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{operation_name} failed without an exception.")
