"""Health check response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Standard health response schema."""

    status: Literal["ok", "degraded", "error"] = Field(
        ...,
        description="Overall service operational health status.",
        examples=["ok"],
    )
    service: str = Field(
        default="decisionvault",
        description="Name of the service.",
        examples=["decisionvault"],
    )
    version: str = Field(
        default="0.1.0",
        description="Service deployment version.",
        examples=["0.1.0"],
    )
    database: Literal["connected", "disconnected", "unreachable"] = Field(
        default="connected",
        description="PostgreSQL database reachability status.",
        examples=["connected"],
    )
    environment: str = Field(
        default="development",
        description="Runtime environment tier.",
        examples=["development"],
    )
