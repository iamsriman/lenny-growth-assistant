from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.llm.registry import (
    active_model_name,
    active_provider_name,
    available_providers,
    clear_overrides,
    provider_statuses,
    set_override,
)
from app.rag.retriever import get_index
from app.schemas.chat import ConfigUpdate

router = APIRouter(prefix="/api/config", tags=["config"])


def _snapshot() -> dict:
    index = get_index()
    return {
        "active": {"provider": active_provider_name(), "model": active_model_name()},
        "configured_default": {"provider": settings.llm_provider,
                               "model": settings.model_for(settings.llm_provider)},
        "fallback_provider": settings.llm_fallback_provider or None,
        "embedding_provider": settings.embedding_provider,
        "providers": available_providers(),
        "models": {name: settings.model_for(name) for name in available_providers()},
        "knowledge_base": {"chunks": index.size,
                           "embedding_model": index.embedding_model,
                           "ready": index.ready},
        "retrieval": {"top_k": settings.retrieval_top_k,
                      "min_score": settings.retrieval_min_score},
        "artifacts": {"scripts_allowed": settings.allow_artifact_scripts},
        "environment": settings.environment,
    }


@router.get("")
async def read_config() -> dict:
    return _snapshot()


@router.get("/providers")
async def providers() -> dict:
    return {"providers": [p.__dict__ for p in await provider_statuses()],
            "active": active_provider_name()}


@router.patch("")
async def update_config(payload: ConfigUpdate) -> dict:
    """Runtime model toggle. Process-local and deliberately unauthenticated —
    this is an internal tool. See architecture.md, "Security posture"."""
    if payload.provider is None and payload.model is None:
        clear_overrides()
    else:
        set_override(provider=payload.provider, model=payload.model)
    return _snapshot()
