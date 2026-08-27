"""Unit tests for error handling and exception formatting."""

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.core.errors import (
    AppException,
    DatabaseConnectionError,
    ResourceNotFoundError,
    register_error_handlers,
)


@pytest.fixture
def error_test_app() -> FastAPI:
    """Creates a minimal test application with error handlers registered."""
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/trigger-app-exception")
    def trigger_app_exception():
        raise AppException(
            message="Custom failure occurred",
            error_code="TEST_FAILURE",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"field": "test_param"},
        )

    @test_app.get("/trigger-not-found")
    def trigger_not_found():
        raise ResourceNotFoundError("Specific item was not found")

    @test_app.get("/trigger-db-error")
    def trigger_db_error():
        raise DatabaseConnectionError("PostgreSQL pool exhausted")

    @test_app.get("/trigger-unhandled")
    def trigger_unhandled():
        # Deliberate division by zero
        return 1 / 0

    return test_app


@pytest.mark.asyncio
async def test_app_exception_handling(error_test_app: FastAPI):
    """Verify AppException translates to formatted JSON response with custom code."""
    transport = ASGITransport(app=error_test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/trigger-app-exception")
        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "TEST_FAILURE"
        assert data["message"] == "Custom failure occurred"
        assert data["details"] == {"field": "test_param"}


@pytest.mark.asyncio
async def test_resource_not_found_exception(error_test_app: FastAPI):
    """Verify ResourceNotFoundError produces a 404 response."""
    transport = ASGITransport(app=error_test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/trigger-not-found")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "RESOURCE_NOT_FOUND"
        assert data["message"] == "Specific item was not found"


@pytest.mark.asyncio
async def test_db_connection_exception(error_test_app: FastAPI):
    """Verify DatabaseConnectionError produces a 503 response."""
    transport = ASGITransport(app=error_test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/trigger-db-error")
        assert response.status_code == 503
        data = response.json()
        assert data["error_code"] == "DATABASE_CONNECTION_ERROR"


@pytest.mark.asyncio
async def test_unhandled_exception_sanitization(error_test_app: FastAPI):
    """Verify unhandled exceptions do not leak stack traces to the client."""
    transport = ASGITransport(app=error_test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/trigger-unhandled")
        assert response.status_code == 500
        data = response.json()
        assert data["error_code"] == "INTERNAL_SERVER_ERROR"
        assert "ZeroDivisionError" not in response.text
        assert data["message"] == "An internal server error occurred."
