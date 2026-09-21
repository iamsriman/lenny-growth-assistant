from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=36)
    message: str = Field(..., min_length=1, max_length=8000)
    # Optional manual override of the router, surfaced in the UI as
    # "Answer / Write essay / Build artifact".
    skill: Literal["grounded_answer", "ship30_essay", "artifact"] | None = None
    artifact_kind: Literal["markdown", "html"] | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message cannot be blank")
        return value.strip()


class ChatResponse(BaseModel):
    session_id: str
    message_id: str | None
    content: str
    grounded: bool
    citations: list[dict] = Field(default_factory=list)
    route: dict | None = None
    artifact: dict | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    error: dict | None = None


class ConfigUpdate(BaseModel):
    provider: Literal["ollama", "anthropic", "openai", "groq"] | None = None
    model: str | None = Field(default=None, max_length=120)


class IngestRequest(BaseModel):
    path: str | None = None
    force: bool = False
    prune_stale: bool = False
