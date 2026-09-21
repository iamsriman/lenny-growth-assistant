from __future__ import annotations

import uuid
from datetime import datetime, timezone
UTC = timezone.utc

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base. JSON is used (not JSONB) so the same models run on
    SQLite during tests and on Postgres in every real environment."""

    type_annotation_map = {dict: JSON, list: JSON}


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    # "user metadata" from the brief: who/where the session came from.
    user_id: Mapped[str] = mapped_column(String(120), default="anonymous", index=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="ollama")
    model: Mapped[str] = mapped_column(String(120), default="")
    meta: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Artifact.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    skill: Mapped[str | None] = mapped_column(String(48), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    citations: Mapped[list] = mapped_column(default=list)
    meta: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # markdown | html
    title: Mapped[str] = mapped_column(String(240), default="Untitled artifact")
    source: Mapped[str] = mapped_column(Text)          # exactly what the model produced
    rendered: Mapped[str] = mapped_column(Text)        # sanitised, safe to embed
    sanitiser_report: Mapped[dict] = mapped_column(default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[ChatSession] = relationship(back_populates="artifacts")


class TranscriptDocument(Base):
    __tablename__ = "transcript_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(400))
    guest: Mapped[str | None] = mapped_column(String(240), nullable=True)
    show: Mapped[str] = mapped_column(String(120), default="Lenny's Podcast")
    url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    chunks: Mapped[list[TranscriptChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(String(160), nullable=True)
    start_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list] = mapped_column(default=list)
    embedding_model: Mapped[str] = mapped_column(String(120), default="")

    document: Mapped[TranscriptDocument] = relationship(back_populates="chunks")


Index("ix_chunk_doc_ordinal", TranscriptChunk.document_id, TranscriptChunk.ordinal)


class RunEvent(Base):
    """Lightweight observability trail — one row per agent run leg.

    Kept in Postgres so failures are diagnosable after the container is gone.
    """

    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    component: Mapped[str] = mapped_column(String(32))
    event: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="ok")
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
