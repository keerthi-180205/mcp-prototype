"""Structured logging configuration with contextual fields and secret scrubbing.

Provides consistent logging across all components (GitHub, External Connectors,
Validation, Gemini, Server) with timestamp, component, operation, status,
duration, and automatic masking of credentials.
"""

import logging
import re
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Dict, Generator, Optional

from server.config import get_settings

# Patterns to sanitize from log messages
SENSITIVE_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
    re.compile(r"(Basic\s+)[A-Za-z0-9+/=]{8,}", re.IGNORECASE),
    re.compile(r"(api[_\-]?key\s*[:=]\s*)[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
    re.compile(r"(token\s*[:=]\s*)[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
]


class SecretScrubbingFilter(logging.Filter):
    """Logging filter that scrubs tokens, authorization headers, and API keys from records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.scrub_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.scrub_text(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self.scrub_text(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True

    @staticmethod
    def scrub_text(text: str) -> str:
        for pattern in SENSITIVE_PATTERNS:
            text = pattern.sub(r"\1[REDACTED]", text)
        return text


class StructuredFormatter(logging.Formatter):
    """Custom formatter producing readable, structured log entries with standard fields."""

    def format(self, record: logging.LogRecord) -> str:
        # Default standard format
        return super().format(record)


def configure_logging(level: Optional[str] = None) -> None:
    """Configure root logger with structured formatting and secret scrubbing."""
    settings = get_settings()
    log_level_str = level or settings.log_level
    log_level = getattr(logging, log_level_str, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if already configured
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(SecretScrubbingFilter())
        root_logger.addHandler(handler)
    else:
        # Ensure filter is attached to existing handlers
        for handler in root_logger.handlers:
            handler.addFilter(SecretScrubbingFilter())


def get_logger(name: str) -> logging.Logger:
    """Retrieve a logger equipped with secret scrubbing."""
    logger = logging.getLogger(name)
    logger.addFilter(SecretScrubbingFilter())
    return logger


class OperationContext:
    """Context object allowing an active operation to report its status and details."""

    def __init__(self, component: str, operation: str) -> None:
        self.component = component
        self.operation = operation
        self.status: str = "success"
        self.details: Dict[str, Any] = {}

    def set_status(self, status: str) -> None:
        self.status = status

    def set_detail(self, key: str, value: Any) -> None:
        self.details[key] = value


@asynccontextmanager
async def async_timed_operation(
    logger: logging.Logger,
    component: str,
    operation: str,
    **initial_details: Any,
) -> AsyncGenerator[OperationContext, None]:
    """Asynchronous context manager measuring duration and emitting structured logs on completion."""
    ctx = OperationContext(component, operation)
    ctx.details.update(initial_details)
    start_time = time.perf_counter()

    try:
        yield ctx
    except Exception as exc:
        ctx.status = "failed"
        duration = time.perf_counter() - start_time
        details_str = " ".join(f"{k}={v}" for k, v in ctx.details.items())
        if details_str:
            details_str = " " + details_str
        logger.error(
            "%s.%s status=failed duration=%.2fs%s error=%s",
            component,
            operation,
            duration,
            details_str,
            type(exc).__name__,
        )
        raise
    else:
        duration = time.perf_counter() - start_time
        details_str = " ".join(f"{k}={v}" for k, v in ctx.details.items())
        if details_str:
            details_str = " " + details_str
        logger.info(
            "%s.%s status=%s duration=%.2fs%s",
            component,
            operation,
            ctx.status,
            duration,
            details_str,
        )


@contextmanager
def timed_operation(
    logger: logging.Logger,
    component: str,
    operation: str,
    **initial_details: Any,
) -> Generator[OperationContext, None, None]:
    """Synchronous context manager measuring duration and emitting structured logs on completion."""
    ctx = OperationContext(component, operation)
    ctx.details.update(initial_details)
    start_time = time.perf_counter()

    try:
        yield ctx
    except Exception as exc:
        ctx.status = "failed"
        duration = time.perf_counter() - start_time
        details_str = " ".join(f"{k}={v}" for k, v in ctx.details.items())
        if details_str:
            details_str = " " + details_str
        logger.error(
            "%s.%s status=failed duration=%.2fs%s error=%s",
            component,
            operation,
            duration,
            details_str,
            type(exc).__name__,
        )
        raise
    else:
        duration = time.perf_counter() - start_time
        details_str = " ".join(f"{k}={v}" for k, v in ctx.details.items())
        if details_str:
            details_str = " " + details_str
        logger.info(
            "%s.%s status=%s duration=%.2fs%s",
            component,
            operation,
            ctx.status,
            duration,
            details_str,
        )
