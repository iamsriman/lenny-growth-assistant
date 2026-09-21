from __future__ import annotations

import time

from fastapi import APIRouter

from app import __version__
from app.config import settings
from app.db.session import db_health
from app.llm.registry import active_model_name, active_provider_name, provider_statuses
from app.rag.retriever import get_index

router = APIRouter(tags=["health"])
_BOOTED = time.time()


@router.get("/health")
async def health() -> dict:
    """Liveness. Never touches a dependency — used by Docker's healthcheck."""
    return {"status": "ok", "version": __version__, "uptime_s": round(time.time() - _BOOTED)}


@router.get("/health/ready")
async def ready() -> dict:
    """Readiness. Reports every dependency separately so a partial outage is
    visible: the app stays useful with a cold index or a down cloud provider."""
    database = await db_health()
    index = get_index()
    providers = [p.__dict__ for p in await provider_statuses()]
    active = active_provider_name()
    active_ok = next((p["available"] for p in providers if p["name"] == active), False)

    checks = {
        "database": database,
        "knowledge_base": {
            "status": "ok" if index.ready else "empty",
            "chunks": index.size,
            "embedding_model": index.embedding_model,
            "hint": "" if index.ready else
                    "Run: docker compose exec api python -m app.rag.ingest",
        },
        "llm": {
            "status": "ok" if active_ok else "degraded",
            "active_provider": active,
            "active_model": active_model_name(),
            "fallback": settings.llm_fallback_provider or None,
            "providers": providers,
        },
    }
    overall = "ok"
    if database["status"] != "ok":
        overall = "down"
    elif not index.ready or not active_ok:
        overall = "degraded"
    return {"status": overall, "version": __version__, "environment": settings.environment,
            "checks": checks}
