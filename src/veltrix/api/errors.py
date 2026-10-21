"""Centralized exception handling classes and decorators following reference project conventions."""

import functools
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from veltrix.core.logging import get_logger

logger = get_logger("errors")


class VeltrixError(Exception):
    """Base exception for all Veltrix PeopleOps operations.

    Captures error messages that may be logged or returned to callers.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class AuthenticationError(VeltrixError):
    """Raised when X-Employee-Id is missing or invalid (HTTP 401)."""


class ForbiddenError(VeltrixError):
    """Raised when session belongs to another employee (HTTP 403)."""


class ValidationError(VeltrixError):
    """Raised when request payload or parameters are invalid (HTTP 400)."""


class ServiceUnavailableError(VeltrixError):
    """Raised when service or ingestion is not yet ready (HTTP 503)."""


class CorpusTokenBudgetExceededError(VeltrixError):
    """Raised when prompt exceeds the 3,000 corpus tokens limit."""


class LLMError(VeltrixError):
    """Raised when LLM call fails or times out."""


class ToolError(VeltrixError):
    """Raised when tool execution encounters an error."""


def handle_http_exceptions(func: Callable) -> Callable:
    """Decorator to handle HTTP exceptions consistently for external HTTP calls (e.g. LLM SDKs)."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as http_error:
            logger.error("HTTP status error", error=str(http_error))
            raise LLMError(f"HTTP error: {http_error}") from http_error
        except httpx.TimeoutException as timeout_error:
            logger.error("Request timeout", error=str(timeout_error))
            raise LLMError(f"Request timeout: {timeout_error}") from timeout_error
        except httpx.RequestError as request_error:
            logger.error("Request failed", error=str(request_error))
            raise LLMError(f"Request error: {request_error}") from request_error
        except Exception as error:
            logger.error("Unexpected error during external call", error=str(error))
            raise

    return wrapper


def handle_tool_exceptions(tool_name: str) -> Callable:
    """Decorator for centralized exception handling in tools, returning structured error responses.

    Args:
        tool_name: Name of the tool for error reporting.

    Returns:
        Decorated function that catches exceptions and returns error dict.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await func(*args, **kwargs)
            except VeltrixError as e:
                logger.error(f"{tool_name} domain error", error=str(e))
                return {
                    "status": "error",
                    "error_message": str(e),
                }
            except ValueError as e:
                logger.error(f"{tool_name} validation error", error=str(e))
                return {
                    "status": "error",
                    "error_message": f"Validation error: {e}",
                }
            except Exception as e:
                logger.error(f"{tool_name} unexpected error", error=str(e))
                return {
                    "status": "error",
                    "error_message": f"Internal error: {e}",
                }

        return wrapper

    return decorator


async def authentication_error_handler(_request: Request, exc: AuthenticationError) -> JSONResponse:
    """Handle 401 AuthenticationError."""
    return JSONResponse(status_code=401, content={"detail": exc.message})


async def forbidden_error_handler(_request: Request, exc: ForbiddenError) -> JSONResponse:
    """Handle 403 ForbiddenError."""
    return JSONResponse(status_code=403, content={"detail": exc.message})


async def validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    """Handle 400 ValidationError."""
    return JSONResponse(status_code=400, content={"detail": exc.message})


async def service_unavailable_handler(
    _request: Request, exc: ServiceUnavailableError
) -> JSONResponse:
    """Handle 503 ServiceUnavailableError."""
    return JSONResponse(status_code=503, content={"status": "not_ready", "detail": exc.message})
