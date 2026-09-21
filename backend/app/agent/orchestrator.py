"""Agent orchestration.

One entry point, `run_turn`, that yields a stream of typed events. The HTTP
layer turns those into SSE; the non-streaming endpoint drains the same
generator. Having a single code path means the streaming and blocking APIs can
never disagree about what the agent did.

Event types: status | route | citations | token | artifact | done | error
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import router as router_mod
from app.agent.router import SKILL_ARTIFACT, SKILL_QA, SKILL_SHIP30
from app.agent.skills import artifact as artifact_skill
from app.agent.skills import qa as qa_skill
from app.agent.skills import ship30
from app.config import settings
from app.db.models import Artifact, ChatSession, Message, RunEvent
from app.llm.base import ChatMessage, LLMError
from app.llm.registry import (
    active_model_name,
    active_provider_name,
    generate_with_fallback,
    stream_with_fallback,
)
from app.logging_config import request_id_var
from app.rag.retriever import RetrievalResult, retrieve
from app.security.sanitizer import sanitize_html, sanitize_markdown, strip_code_fence

log = logging.getLogger("app.agent")


@dataclass
class Event:
    type: str
    data: dict[str, Any]


def _event(event_type: str, **data) -> Event:
    return Event(event_type, data)


async def _log_event(db: AsyncSession, session_id: str | None, component: str,
                     event: str, *, status: str = "ok", duration_ms: float | None = None,
                     **detail) -> None:
    db.add(RunEvent(session_id=session_id, request_id=request_id_var.get(),
                    component=component, event=event, status=status,
                    duration_ms=duration_ms, detail=detail))
    await db.flush()


async def _history(db: AsyncSession, session_id: str, limit: int) -> list[Message]:
    rows = (await db.execute(
        select(Message).where(Message.session_id == session_id)
        .order_by(Message.created_at.desc()).limit(limit)
    )).scalars().all()
    return list(reversed(rows))


def _to_chat(messages: list[Message]) -> list[ChatMessage]:
    return [ChatMessage(m.role, m.content) for m in messages
            if m.role in ("user", "assistant") and m.content.strip()]


def _digest(messages: list[Message], limit: int = 900) -> str:
    parts = []
    for m in messages[-6:]:
        who = "User" if m.role == "user" else "Assistant"
        parts.append(f"{who}: {m.content[:260]}")
    return "\n".join(parts)[-limit:]


def _retrieval_query(user_message: str, history: list[Message]) -> str:
    """Follow-ups like "what about B2B?" retrieve nothing on their own, so we
    prepend the last user turn as context for the embedding query only."""
    if len(user_message.split()) >= 8:
        return user_message
    previous = [m.content for m in history if m.role == "user"]
    if previous:
        return f"{previous[-1]} {user_message}"
    return user_message


async def run_turn(
    db: AsyncSession,
    session: ChatSession,
    user_text: str,
    *,
    force_skill: str | None = None,
    artifact_kind: str | None = None,
) -> AsyncIterator[Event]:
    t0 = time.perf_counter()
    provider_name = active_provider_name()
    model_name = active_model_name()

    history = await _history(db, session.id, settings.history_turns)

    user_msg = Message(session_id=session.id, role="user", content=user_text)
    db.add(user_msg)
    await db.flush()

    if session.title in ("", "New chat"):
        session.title = (user_text.strip().splitlines()[0] or "New chat")[:80]
    session.provider = provider_name
    session.model = model_name

    yield _event("status", stage="routing", provider=provider_name, model=model_name)

    if force_skill:
        decision = router_mod.RouteDecision(force_skill, "explicitly requested by the user",
                                            1.0, artifact_kind=artifact_kind, stage="forced")
    else:
        decision = await router_mod.route(user_text)
        if artifact_kind and decision.skill == SKILL_ARTIFACT:
            decision.artifact_kind = artifact_kind

    yield _event("route", **decision.as_dict())
    await _log_event(db, session.id, "agent", "route", **decision.as_dict())

    # ---- retrieval ----------------------------------------------------
    yield _event("status", stage="retrieving")
    try:
        result = await retrieve(_retrieval_query(user_text, history),
                               top_k=10 if decision.skill == SKILL_SHIP30
                               else settings.retrieval_top_k)
    except Exception as exc:  # noqa: BLE001
        log.exception("retrieval failed", extra={"component": "retrieval"})
        await _log_event(db, session.id, "retrieval", "error", status="error", error=str(exc))
        result = RetrievalResult(note=f"Retrieval failed: {exc}")

    citations = result.citations()
    yield _event("citations", citations=citations, grounded=result.grounded,
                 top_score=round(result.top_score, 4), degraded=result.degraded,
                 took_ms=round(result.took_ms, 1), note=result.note)
    await _log_event(db, session.id, "retrieval", "retrieve",
                     duration_ms=result.took_ms, hits=len(citations),
                     grounded=result.grounded, degraded=result.degraded)

    context_block = result.context_block()

    # ---- generation ---------------------------------------------------
    text = ""
    used_provider = provider_name
    artifact_row: Artifact | None = None
    meta: dict = {"route": decision.as_dict(), "retrieval": {
        "grounded": result.grounded, "top_score": round(result.top_score, 4),
        "degraded": result.degraded, "hits": len(citations)}}

    try:
        if decision.skill == SKILL_QA:
            system = qa_skill.SYSTEM if result.grounded else qa_skill.NO_CONTEXT_SYSTEM
            prompt = qa_skill.build_user_prompt(user_text, context_block, result.grounded)
            messages = _to_chat(history) + [ChatMessage("user", prompt)]
            yield _event("status", stage="generating", skill=decision.skill)
            async for token, prov in stream_with_fallback(messages, system=system):
                used_provider = prov
                text += token
                yield _event("token", text=token)

        elif decision.skill == SKILL_SHIP30:
            yield _event("status", stage="generating", skill=decision.skill,
                         note="drafting essay")
            system = ship30.build_system_prompt()
            prompt = ship30.build_user_prompt(user_text, context_block, _digest(history))
            draft, used_provider, _ = await generate_with_fallback(
                [ChatMessage("user", prompt)], system=system,
                temperature=0.6, max_tokens=4096,
            )
            draft = strip_code_fence(draft)
            critique = ship30.validate(draft)
            yield _event("status", stage="critiquing", skill=decision.skill,
                         critique=critique.as_dict())
            await _log_event(db, session.id, "agent", "ship30_critique", **critique.as_dict())

            if not critique.passed:
                yield _event("status", stage="revising", skill=decision.skill,
                             note=f"{len(critique.failures)} issue(s) to fix")
                revision_prompt = ship30.build_revision_prompt(draft, critique, context_block)
                try:
                    revised, used_provider, _ = await generate_with_fallback(
                        [ChatMessage("user", revision_prompt)], system=system,
                        temperature=0.5, max_tokens=4096,
                    )
                    if ship30.word_count(revised) > ship30.word_count(draft) * 0.6:
                        after = ship30.validate(revised)
                        # Keep the revision only if it actually improved.
                        if after.score >= critique.score:
                            draft, critique = revised, after
                except LLMError as exc:
                    log.warning("revision pass failed, keeping draft",
                                extra={"component": "agent", "error": str(exc)})

            text = draft
            meta["critique"] = critique.as_dict()
            content, report = sanitize_markdown(text)
            artifact_row = Artifact(
                session_id=session.id, kind="markdown",
                title=ship30.extract_title(content), source=text,
                rendered=content, sanitiser_report=report,
            )
            for piece in _chunks_for_stream(text):
                yield _event("token", text=piece)

        else:  # SKILL_ARTIFACT
            kind = decision.artifact_kind or "markdown"
            yield _event("status", stage="generating", skill=decision.skill,
                         artifact_kind=kind)
            system = (artifact_skill.HTML_SYSTEM if kind == "html"
                      else artifact_skill.MARKDOWN_SYSTEM)
            prompt = artifact_skill.build_user_prompt(
                user_text, context_block, _digest(history), kind
            )
            raw, used_provider, _ = await generate_with_fallback(
                [ChatMessage("user", prompt)], system=system,
                temperature=0.4, max_tokens=4096,
            )
            if len(raw.encode()) > settings.artifact_max_bytes:
                raw = raw[: settings.artifact_max_bytes]
                meta["artifact_truncated"] = True

            if kind == "html":
                rendered, report = sanitize_html(
                    raw, allow_scripts=settings.allow_artifact_scripts
                )
            else:
                rendered, report = sanitize_markdown(raw)

            title = artifact_skill.extract_title(rendered, kind, user_text)
            artifact_row = Artifact(session_id=session.id, kind=kind, title=title,
                                    source=raw, rendered=rendered,
                                    sanitiser_report=report)
            removed = report.get("removed") or []
            text = (f"I built **{title}** and opened it in the artifact viewer."
                    + (f"\n\nThe sanitiser removed: {', '.join(removed)}."
                       if removed else "")
                    + ("\n\nNote: no transcript passage cleared the grounding threshold, "
                       "so this is structure rather than sourced content."
                       if not result.grounded else ""))
            for piece in _chunks_for_stream(text):
                yield _event("token", text=piece)

    except LLMError as exc:
        await _log_event(db, session.id, "llm", "error", status="error",
                         kind=exc.kind, provider=exc.provider, error=str(exc))
        log.error("generation failed", extra={"component": "llm", "kind": exc.kind,
                                              "provider": exc.provider, "error": str(exc)})
        yield _event("error", message=str(exc), kind=exc.kind, provider=exc.provider,
                     remediation=_remediation(exc), request_id=request_id_var.get())
        await db.commit()
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("unhandled agent failure", extra={"component": "agent"})
        await _log_event(db, session.id, "agent", "error", status="error", error=str(exc))
        yield _event("error", message="The assistant hit an unexpected error.",
                     kind="internal", provider=provider_name,
                     remediation="Check the backend logs for the request id.",
                     request_id=request_id_var.get())
        await db.commit()
        return

    latency_ms = int((time.perf_counter() - t0) * 1000)
    assistant = Message(
        session_id=session.id, role="assistant", content=text, skill=decision.skill,
        provider=used_provider, model=model_name, latency_ms=latency_ms,
        grounded=result.grounded, citations=citations, meta=meta,
    )
    db.add(assistant)
    await db.flush()

    artifact_payload = None
    if artifact_row is not None:
        artifact_row.message_id = assistant.id
        db.add(artifact_row)
        await db.flush()
        artifact_payload = {
            "id": artifact_row.id, "kind": artifact_row.kind,
            "title": artifact_row.title, "content": artifact_row.rendered,
            "sanitiser_report": artifact_row.sanitiser_report,
            "created_at": artifact_row.created_at.isoformat()
            if artifact_row.created_at else None,
        }
        yield _event("artifact", **artifact_payload)

    await _log_event(db, session.id, "agent", "turn_complete", duration_ms=latency_ms,
                     skill=decision.skill, provider=used_provider,
                     grounded=result.grounded, chars=len(text))
    await db.commit()

    yield _event("done", message_id=assistant.id, skill=decision.skill,
                 provider=used_provider, model=model_name, latency_ms=latency_ms,
                 grounded=result.grounded, session_title=session.title,
                 artifact_id=artifact_row.id if artifact_row else None)


def _chunks_for_stream(text: str, size: int = 120) -> list[str]:
    """Skills that need the whole document before validating still stream out,
    so the UI behaves identically for every skill."""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def _remediation(exc: LLMError) -> str:
    return {
        "unavailable": "Start Ollama (`ollama serve`) or switch the provider in the "
                       "model menu.",
        "model_missing": "Pull the model, then retry.",
        "timeout": "The model took too long. Try a smaller model "
                   "(e.g. llama3.2:1b) or raise LLM_TIMEOUT_SECONDS.",
        "missing_key": "Add the provider's API key to .env and restart the backend.",
        "auth": "The API key was rejected. Check it in .env.",
        "rate_limit": "Rate limited. Wait a moment or switch provider.",
    }.get(exc.kind, "Check the backend logs for details.")


async def drain(events: AsyncIterator[Event]) -> dict:
    """Collect a full turn into one response object (non-streaming endpoint)."""
    out: dict = {"content": "", "citations": [], "route": None, "artifact": None,
                 "error": None, "grounded": False, "message_id": None,
                 "provider": None, "model": None, "latency_ms": None}
    async for ev in events:
        if ev.type == "token":
            out["content"] += ev.data.get("text", "")
        elif ev.type == "citations":
            out["citations"] = ev.data.get("citations", [])
            out["grounded"] = ev.data.get("grounded", False)
        elif ev.type == "route":
            out["route"] = ev.data
        elif ev.type == "artifact":
            out["artifact"] = ev.data
        elif ev.type == "error":
            out["error"] = ev.data
        elif ev.type == "done":
            out.update({k: ev.data.get(k) for k in
                        ("message_id", "provider", "model", "latency_ms")})
            out["grounded"] = ev.data.get("grounded", out["grounded"])
    return out
