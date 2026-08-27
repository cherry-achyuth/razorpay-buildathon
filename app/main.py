"""DecisionVault FastAPI Application entrypoint."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.models  # noqa: F401
from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import RequestLoggingMiddleware, logger, setup_logging
from app.db.session import check_db_connectivity, close_db_engine, get_engine
from app.schemas.health import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager for startup and graceful shutdown."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        "Initializing %s v%s in %s mode...",
        settings.PROJECT_NAME,
        settings.VERSION,
        settings.APP_ENV,
    )

    # Initialize database engine pool & test connectivity
    try:
        get_engine()
        db_healthy = await check_db_connectivity()
        if db_healthy:
            logger.info("PostgreSQL database connection established.")
        else:
            logger.warning("PostgreSQL database is unreachable.")
    except Exception as exc:
        logger.error("Failed to initialize database engine: %s", exc)

    yield

    # Clean shutdown
    logger.info("Shutting down %s...", settings.PROJECT_NAME)
    await close_db_engine()
    logger.info("Shutdown complete.")


def create_application() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()

    app = FastAPI(
        title=f"{settings.PROJECT_NAME} API",
        description=(
            "Decision-Preserving Financial Memory for Autonomous Agents. "
            "DecisionVault sits between AI buying agents and payment "
            "execution gateways to ensure explainable financial actions."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Setup CORS
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Register error handlers
    register_error_handlers(app)

    # Include root /health endpoint
    @app.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        tags=["Health"],
        summary="Root Health Check Probe",
        description="Returns service status, version, and database connectivity.",
    )
    async def root_health_check() -> JSONResponse:
        db_connected = await check_db_connectivity()
        overall_status = "ok" if db_connected else "degraded"
        db_status = "connected" if db_connected else "unreachable"

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": overall_status,
                "service": settings.PROJECT_NAME.lower(),
                "version": settings.VERSION,
                "database": db_status,
                "environment": settings.APP_ENV,
            },
        )

    # Include versioned API routers
    app.include_router(api_router, prefix=settings.API_V1_STR)

    # Mount static assets & serve Buildathon Demo Dashboard
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        @app.get("/demo", include_in_schema=False)
        async def serve_demo_dashboard() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app


app = create_application()
