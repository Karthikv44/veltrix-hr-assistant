"""Unit tests for exception classes and decorators following reference repo pattern."""

import httpx
import pytest

from veltrix.api.errors import (
    AuthenticationError,
    ForbiddenError,
    LLMError,
    ServiceUnavailableError,
    ValidationError,
    VeltrixError,
    handle_http_exceptions,
    handle_tool_exceptions,
)


class TestVeltrixErrors:
    """Test custom exception classes."""

    def test_error_creation(self) -> None:
        err = VeltrixError("Base error")
        assert str(err) == "Base error"
        assert err.message == "Base error"
        assert isinstance(err, Exception)

    def test_subclass_inheritance(self) -> None:
        assert issubclass(AuthenticationError, VeltrixError)
        assert issubclass(ForbiddenError, VeltrixError)
        assert issubclass(ValidationError, VeltrixError)
        assert issubclass(ServiceUnavailableError, VeltrixError)


class TestHandleHttpExceptions:
    """Test handle_http_exceptions decorator matching reference repo behavior."""

    @pytest.mark.asyncio
    async def test_successful_request(self) -> None:
        @handle_http_exceptions
        async def mock_call() -> dict[str, str]:
            return {"status": "ok"}

        result = await mock_call()
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_http_status_error(self) -> None:
        @handle_http_exceptions
        async def mock_call() -> None:
            request = httpx.Request("GET", "http://test.example")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("Not Found", request=request, response=response)

        with pytest.raises(LLMError) as exc_info:
            await mock_call()
        assert "HTTP error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_exception(self) -> None:
        @handle_http_exceptions
        async def mock_call() -> None:
            raise httpx.TimeoutException("Timed out")

        with pytest.raises(LLMError) as exc_info:
            await mock_call()
        assert "Request timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_request_error(self) -> None:
        @handle_http_exceptions
        async def mock_call() -> None:
            raise httpx.RequestError("Connection failed")

        with pytest.raises(LLMError) as exc_info:
            await mock_call()
        assert "Request error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unexpected_exception(self) -> None:
        @handle_http_exceptions
        async def mock_call() -> None:
            raise RuntimeError("Fatal internal error")

        with pytest.raises(RuntimeError):
            await mock_call()


class TestHandleToolExceptions:
    """Test handle_tool_exceptions decorator for tools returning structured dicts."""

    @pytest.mark.asyncio
    async def test_successful_tool_execution(self) -> None:
        @handle_tool_exceptions("test_tool")
        async def mock_tool() -> dict[str, str]:
            return {"status": "success", "result": "done"}

        result = await mock_tool()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_domain_error_handling(self) -> None:
        @handle_tool_exceptions("test_tool")
        async def mock_tool() -> None:
            raise VeltrixError("Domain rule failure")

        result = await mock_tool()
        assert result["status"] == "error"
        assert "Domain rule failure" in result["error_message"]

    @pytest.mark.asyncio
    async def test_validation_error_handling(self) -> None:
        @handle_tool_exceptions("test_tool")
        async def mock_tool() -> None:
            raise ValueError("Invalid date range")

        result = await mock_tool()
        assert result["status"] == "error"
        assert "Validation error" in result["error_message"]

    @pytest.mark.asyncio
    async def test_unexpected_error_handling(self) -> None:
        @handle_tool_exceptions("test_tool")
        async def mock_tool() -> None:
            raise RuntimeError("Database crash")

        result = await mock_tool()
        assert result["status"] == "error"
        assert "Internal error" in result["error_message"]
