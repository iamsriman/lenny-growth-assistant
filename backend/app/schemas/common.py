from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Every non-2xx response in this API has this shape."""

    code: str = Field(..., examples=["provider_unavailable"])
    message: str
    remediation: str | None = None
    request_id: str | None = None
    detail: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Page(BaseModel):
    total: int
    limit: int
    offset: int
