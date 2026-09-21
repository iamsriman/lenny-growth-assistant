from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import TranscriptChunk, TranscriptDocument
from app.db.session import get_db
from app.rag.ingest import ingest_path
from app.rag.retriever import get_index, refresh_index, retrieve
from app.schemas.chat import IngestRequest

log = logging.getLogger("app.api.knowledge")
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(
        select(TranscriptDocument).order_by(TranscriptDocument.title)
    )).scalars().all()
    total_chunks = (await db.execute(select(func.count(TranscriptChunk.id)))).scalar() or 0
    return {
        "documents": [
            {"id": d.id, "external_id": d.external_id, "title": d.title, "guest": d.guest,
             "url": d.url, "published_at": d.published_at, "synthetic": d.synthetic,
             "chunks": d.n_chunks,
             "ingested_at": d.ingested_at.isoformat() if d.ingested_at else None}
            for d in rows
        ],
        "total_documents": len(rows),
        "total_chunks": total_chunks,
        "index_chunks": get_index().size,
        "embedding_model": get_index().embedding_model,
        "synthetic_present": any(d.synthetic for d in rows),
    }


@router.post("/ingest")
async def trigger_ingest(payload: IngestRequest,
                         db: AsyncSession = Depends(get_db)) -> dict:
    report = await ingest_path(db, payload.path or settings.transcripts_dir,
                               force=payload.force, prune_stale=payload.prune_stale)
    return report.as_dict()


@router.post("/reconcile")
async def reconcile_current_transcripts(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Make the persisted corpus exactly match the configured transcript directory."""
    report = await ingest_path(db, settings.transcripts_dir, force=True, prune_stale=True)
    return report.as_dict()


@router.post("/reindex")
async def reindex(db: AsyncSession = Depends(get_db)) -> dict:
    size = await refresh_index(db)
    return {"chunks": size, "embedding_model": get_index().embedding_model}


@router.get("/search")
async def search(q: str = Query(..., min_length=2, max_length=500),
                 k: int = Query(default=6, ge=1, le=20)) -> dict:
    """Retrieval without generation — the fastest way to debug grounding."""
    result = await retrieve(q, top_k=k)
    return {"query": q, "grounded": result.grounded,
            "top_score": round(result.top_score, 4),
            "degraded": result.degraded, "took_ms": round(result.took_ms, 1),
            "note": result.note, "results": result.citations()}
