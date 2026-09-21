from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    user_id: str = Field(default="anonymous", max_length=120)
    meta: dict = Field(default_factory=dict)


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


class CitationOut(BaseModel):
    index: int
    chunk_id: str | None = None
    document_id: str | None = None
    title: str
    guest: str | None = None
    url: str | None = None
    speaker: str | None = None
    timestamp: str | None = None
    synthetic: bool = False
    score: float = 0.0
    quote: str = ""


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    skill: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    grounded: bool = False
    citations: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    created_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    user_id: str
    provider: str
    model: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionDetail(SessionOut):
    messages: list[MessageOut] = Field(default_factory=list)
    artifacts: list[ArtifactSummary] = Field(default_factory=list)


class ArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    version: int
    created_at: datetime


class ArtifactOut(ArtifactSummary):
    session_id: str
    message_id: str | None = None
    content: str
    sanitiser_report: dict = Field(default_factory=dict)


SessionDetail.model_rebuild()
