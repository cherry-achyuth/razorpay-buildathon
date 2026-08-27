"""Structured logging setup for DecisionVault."""

import logging
import sys
import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Sensitive keys that should never appear in log payloads
SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "card_number",
    "cvv",
    "razorpay_signature",
    "key_secret",
}


def sanitize_data(data: dict) -> dict:
    """Masks sensitive fields in dictionaries before logging."""
    sanitized = {}
    for key, val in data.items():
        if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
            sanitized[key] = "********"
        elif isinstance(val, dict):
            sanitized[key] = sanitize_data(val)
        else:
            sanitized[key] = val
    return sanitized


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configures application-wide structured logging."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Set logger levels for third-party libraries to prevent log spam
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger = logging.getLogger("decisionvault")
    logger.setLevel(level)
    return logger


logger = logging.getLogger("decisionvault")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log incoming HTTP requests and processing latency."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        # Process the request
        try:
            response = await call_next(request)
            process_time_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "%s %s -> %d (%.2fms) [client: %s]",
                method,
                path,
                response.status_code,
                process_time_ms,
                client_ip,
            )
            return response
        except Exception as exc:
            process_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "%s %s failed with unhandled exception: %s (%.2fms) [client: %s]",
                method,
                path,
                str(exc),
                process_time_ms,
                client_ip,
                exc_info=True,
            )
            raise
