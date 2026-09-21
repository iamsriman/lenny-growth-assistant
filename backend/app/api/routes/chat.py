from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import drain, run_turn
from app.api.routes.sessions import load_session
from app.db.session import db_scope, get_db
from app.logging_config import request_id_var, session_id_var
from app.schemas.chat import ChatRequest, ChatResponse

log = logging.getLogger("app.api.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    """Blocking turn. Same agent path as /stream, collected into one object."""
    session_id_var.set(payload.session_id)
    session = await load_session(payload.session_id, db)
    result = await drain(run_turn(db, session, payload.message,
                                  force_skill=payload.skill,
                                  artifact_kind=payload.artifact_kind))
    return ChatResponse(session_id=session.id, **result)


@router.post("/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """Server-Sent Events.

    Uses its own DB scope rather than the request-scoped dependency, because
    the generator outlives the request handler.
    """
    session_id_var.set(payload.session_id)

    async def event_source():
        try:
            async with db_scope() as db:
                session = await load_session(payload.session_id, db)
                async for event in run_turn(db, session, payload.message,
                                            force_skill=payload.skill,
                                            artifact_kind=payload.artifact_kind):
                    yield f"event: {event.type}\ndata: {json.dumps(event.data, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 - the stream must always close cleanly
            log.exception("stream failed", extra={"component": "api"})
            payload_err = {"message": str(exc)[:400], "kind": "stream_error",
                           "remediation": "Retry, or check the backend logs.",
                           "request_id": request_id_var.get()}
            yield f"event: error\ndata: {json.dumps(payload_err)}\n\n"
        finally:
            yield "event: close\ndata: {}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform",
                 "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )
