from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Artifact
from app.db.session import get_db
from app.schemas.session import ArtifactOut, ArtifactSummary
from app.security.sanitizer import CSP

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


async def _load(artifact_id: str, db: AsyncSession) -> Artifact:
    row = (await db.execute(
        select(Artifact).where(Artifact.id == artifact_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404,
                            detail={"code": "artifact_not_found",
                                    "message": f"No artifact with id '{artifact_id}'."})
    return row


@router.get("", response_model=list[ArtifactSummary])
async def list_artifacts(session_id: str | None = Query(default=None),
                         limit: int = Query(default=50, ge=1, le=200),
                         db: AsyncSession = Depends(get_db)) -> list[ArtifactSummary]:
    stmt = select(Artifact).order_by(Artifact.created_at.desc()).limit(limit)
    if session_id:
        stmt = stmt.where(Artifact.session_id == session_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [ArtifactSummary.model_validate(r) for r in rows]


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(artifact_id: str, db: AsyncSession = Depends(get_db)) -> ArtifactOut:
    row = await _load(artifact_id, db)
    return ArtifactOut(
        id=row.id, kind=row.kind, title=row.title, version=row.version,
        created_at=row.created_at, session_id=row.session_id,
        message_id=row.message_id, content=row.rendered,
        sanitiser_report=row.sanitiser_report or {},
    )


@router.get("/{artifact_id}/raw")
async def get_artifact_raw(artifact_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """The unsanitised model output, for auditing what the sanitiser changed."""
    row = await _load(artifact_id, db)
    return {"id": row.id, "kind": row.kind, "source": row.source,
            "rendered": row.rendered, "sanitiser_report": row.sanitiser_report}


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    row = await _load(artifact_id, db)
    ext = "html" if row.kind == "html" else "md"
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row.title)[:60]
    media = "text/html" if row.kind == "html" else "text/markdown"
    return Response(
        content=row.rendered,
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name or "artifact"}.{ext}"',
            # Even on direct download the document may not call home.
            "Content-Security-Policy": CSP,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/meta/policy")
async def artifact_policy() -> dict:
    """What the viewer permits and blocks — surfaced in the UI 'Security' panel."""
    return {
        "sandbox": "allow-scripts allow-popups allow-modals"
                   if settings.allow_artifact_scripts else "allow-popups",
        "same_origin": False,
        "csp": CSP,
        "blocked": ["<iframe>", "<object>", "<embed>", "<form>", "<base>", "<link>",
                    "meta refresh", "inline on* handlers", "javascript: URLs",
                    "data:text/html URLs", "network requests (connect-src 'none')",
                    "external scripts and stylesheets"],
        "allowed": ["inline <style>", "inline SVG", "images over https: and data:",
                    "form controls (non-submitting)",
                    "one inline <script> with addEventListener"
                    if settings.allow_artifact_scripts else "no scripts"],
        "rationale": "The iframe is cross-origin (no allow-same-origin), so artifact "
                     "script has no access to the app origin, cookies or storage. "
                     "Sanitisation and CSP are defence in depth, not the only line.",
    }
