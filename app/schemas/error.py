"""Standard error response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Granular error field or context."""

    location: str = Field(
        ..., description="Location of the invalid field or parameter."
    )
    message: str = Field(..., description="Explanation of the validation issue.")
    type: str = Field(default="value_error", description="Error categorization code.")


class ErrorResponse(BaseModel):
    """Standardized API error response body."""

    error_code: str = Field(
        ...,
        description="Machine-readable error classification code.",
        examples=["VALIDATION_ERROR", "INTERNAL_SERVER_ERROR"],
    )
    message: str = Field(
        ...,
        description="Human-readable explanation of the error.",
        examples=["Input validation failed"],
    )
    details: list[ErrorDetail] | list[dict[str, Any]] | dict[str, Any] | None = Field(
        default=None,
        description="Optional structured error details or field validation issues.",
    )
