"""Health check endpoints for DecisionVault."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.session import check_db_connectivity
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="System Health and Database Connectivity Probe",
    description="Returns service status, version, and PostgreSQL connectivity.",
)
async def health_check() -> JSONResponse:
    """Performs health check and database reachability verification."""
    settings = get_settings()
    db_connected = await check_db_connectivity()

    overall_status = "ok" if db_connected else "degraded"
    db_status = "connected" if db_connected else "unreachable"

    response_payload = {
        "status": overall_status,
        "service": settings.PROJECT_NAME.lower(),
        "version": settings.VERSION,
        "database": db_status,
        "environment": settings.APP_ENV,
    }

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_payload,
    )
