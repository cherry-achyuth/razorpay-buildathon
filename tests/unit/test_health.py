"""Unit tests for the health check endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_health_endpoint_healthy(async_client: AsyncClient):
    """Test GET /health returns 200 OK and expected structure."""
    with patch(
        "app.main.check_db_connectivity",
        new=AsyncMock(return_value=True),
    ):
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "decisionvault"
        assert "version" in data
        assert data["database"] == "connected"
        assert data["environment"] == "test"


@pytest.mark.asyncio
async def test_root_health_endpoint_degraded(async_client: AsyncClient):
    """Test GET /health reflects degraded status when DB is unreachable."""
    with patch(
        "app.main.check_db_connectivity",
        new=AsyncMock(return_value=False),
    ):
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unreachable"


@pytest.mark.asyncio
async def test_api_v1_health_endpoint(async_client: AsyncClient):
    """Test GET /api/v1/health returns 200 OK and consistent schema."""
    with patch(
        "app.api.v1.routes.health.check_db_connectivity",
        new=AsyncMock(return_value=True),
    ):
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "decisionvault"
        assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_openapi_documentation_accessible(async_client: AsyncClient):
    """Verify OpenAPI JSON schema endpoint is accessible and well-formed."""
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "DecisionVault API"
    assert "/health" in schema["paths"]
