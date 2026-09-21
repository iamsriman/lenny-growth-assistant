from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ChatSession, Message
from app.db.session import get_db
from app.llm.registry import active_model_name, active_provider_name
from app.schemas.session import (
    ArtifactSummary,
    MessageOut,
    SessionCreate,
    SessionDetail,
    SessionOut,
    SessionUpdate,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


async def load_session(session_id: str, db: AsyncSession) -> ChatSession:
    row = (await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "session_not_found",
                                    "message": f"No session with id '{session_id}'.",
                                    "remediation": "Start a new chat."})
    return row


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, request: Request,
                         db: AsyncSession = Depends(get_db)) -> SessionOut:
    row = ChatSession(
        title=payload.title or "New chat",
        user_id=payload.user_id,
        user_agent=(request.headers.get("user-agent") or "")[:400] or None,
        client_ip=request.client.host if request.client else None,
        provider=active_provider_name(),
        model=active_model_name(),
        meta=payload.meta,
    )
    db.add(row)
    await db.flush()
    return SessionOut.model_validate(row)


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    user_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[SessionOut]:
    counts = (
        select(Message.session_id, func.count(Message.id).label("n"))
        .group_by(Message.session_id).subquery()
    )
    stmt = (
        select(ChatSession, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit).offset(offset)
    )
    if user_id:
        stmt = stmt.where(ChatSession.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(ChatSession.archived.is_(False))

    out = []
    for row, count in (await db.execute(stmt)).all():
        item = SessionOut.model_validate(row)
        item.message_count = int(count)
        out.append(item)
    return out


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)) -> SessionDetail:
    row = (await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages), selectinload(ChatSession.artifacts))
        .where(ChatSession.id == session_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404,
                            detail={"code": "session_not_found",
                                    "message": f"No session with id '{session_id}'."})
    detail = SessionDetail.model_validate(row)
    detail.messages = [MessageOut.model_validate(m) for m in row.messages]
    detail.artifacts = [ArtifactSummary.model_validate(a) for a in row.artifacts]
    detail.message_count = len(row.messages)
    return detail


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(session_id: str, payload: SessionUpdate,
                         db: AsyncSession = Depends(get_db)) -> SessionOut:
    row = await load_session(session_id, db)
    if payload.title is not None:
        row.title = payload.title
    if payload.archived is not None:
        row.archived = payload.archived
    await db.flush()
    return SessionOut.model_validate(row)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    row = await load_session(session_id, db)
    await db.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: str, limit: int = Query(default=200, ge=1, le=500),
                        db: AsyncSession = Depends(get_db)) -> list[MessageOut]:
    await load_session(session_id, db)
    rows = (await db.execute(
        select(Message).where(Message.session_id == session_id)
        .order_by(Message.created_at).limit(limit)
    )).scalars().all()
    return [MessageOut.model_validate(r) for r in rows]
