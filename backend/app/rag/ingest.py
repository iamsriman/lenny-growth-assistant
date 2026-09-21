"""Ingestion.

Flow: discover files -> parse -> hash -> skip unchanged -> chunk -> embed ->
upsert -> rebuild index. Re-running is safe and cheap: a document whose
content hash is unchanged is skipped, so `refresh` is the same command as
`load`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import TranscriptChunk, TranscriptDocument
from app.db.session import db_scope, dispose_db, init_db
from app.llm.registry import embed_texts
from app.logging_config import configure_logging
from app.rag.chunker import ParsedTranscript, chunk_turns, discover_transcripts, parse_file
from app.rag.retriever import refresh_index

log = logging.getLogger("app.ingest")


@dataclass
class IngestReport:
    scanned: int = 0
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    chunks: int = 0
    pruned: int = 0
    embedding_model: str = ""
    errors: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned, "ingested": self.ingested, "skipped": self.skipped,
            "failed": self.failed, "chunks": self.chunks,
            "pruned": self.pruned,
            "embedding_model": self.embedding_model,
            "errors": self.errors[:10], "documents": self.documents[:50],
        }


async def ingest_path(
    db: AsyncSession,
    directory: str | Path | None = None,
    *,
    force: bool = False,
    prune_stale: bool = False,
) -> IngestReport:
    directory = Path(directory or settings.transcripts_dir)
    report = IngestReport()
    files = discover_transcripts(directory)
    report.scanned = len(files)
    if not files:
        if prune_stale:
            raise ValueError(f"refusing to prune: no transcript files found in {directory}")
        log.warning("no transcripts found", extra={"component": "ingest",
                                                   "directory": str(directory)})
        return report

    parsed_files: list[tuple[Path, ParsedTranscript]] = []
    for path in files:
        try:
            parsed_files.append((path, parse_file(path)))
        except Exception as exc:  # noqa: BLE001 - refuse pruning on invalid input
            report.failed += 1
            report.errors.append(f"{path.name}: {exc}")
            log.exception("failed to parse transcript",
                          extra={"component": "ingest", "file": path.name})
    if prune_stale and report.failed:
        raise ValueError("cannot prune stale transcripts while current files have parse errors")

    if prune_stale:
        current_ids = {parsed.external_id for _, parsed in parsed_files}
        current_names = {path.name for path, _ in parsed_files}
        existing_docs = (await db.execute(select(TranscriptDocument))).scalars().all()
        for doc in existing_docs:
            source_file = (doc.meta or {}).get("source_file")
            if doc.external_id not in current_ids and source_file not in current_names:
                await db.execute(delete(TranscriptChunk).where(
                    TranscriptChunk.document_id == doc.id
                ))
                await db.delete(doc)
                report.pruned += 1

    for path, parsed in parsed_files:
        try:
            existing = (
            await db.execute(
                select(TranscriptDocument).where(
                    TranscriptDocument.external_id == parsed.external_id
                )
            )
            ).scalar_one_or_none()

            if existing and existing.content_hash == parsed.content_hash and not force:
                report.skipped += 1
                continue

            chunks = chunk_turns(parsed.turns)
            if not chunks:
                report.failed += 1
                report.errors.append(f"{path.name}: produced no usable chunks")
                continue

            vectors, model_label = await embed_texts([c.text for c in chunks])
            report.embedding_model = model_label

            if existing:
                await db.execute(
                    delete(TranscriptChunk).where(TranscriptChunk.document_id == existing.id)
                )
                doc = existing
                doc.title = parsed.title
                doc.guest = parsed.guest
                doc.url = parsed.url
                doc.published_at = parsed.published_at
                doc.synthetic = parsed.synthetic
                doc.content_hash = parsed.content_hash
                doc.meta = parsed.meta
            else:
                doc = TranscriptDocument(
                    external_id=parsed.external_id, title=parsed.title, guest=parsed.guest,
                    url=parsed.url, published_at=parsed.published_at,
                    synthetic=parsed.synthetic, content_hash=parsed.content_hash,
                    meta=parsed.meta,
                )
                db.add(doc)
                await db.flush()

            doc.n_chunks = len(chunks)
            for chunk, vector in zip(chunks, vectors, strict=True):
                db.add(TranscriptChunk(
                    document_id=doc.id, ordinal=chunk.ordinal, text=chunk.text,
                    speaker=chunk.speaker, start_label=chunk.start_label,
                    token_estimate=chunk.token_estimate, embedding=list(vector),
                    embedding_model=model_label,
                ))
            await db.flush()

            report.ingested += 1
            report.chunks += len(chunks)
            report.documents.append(parsed.title)
            log.info("ingested transcript", extra={"component": "ingest", "title": parsed.title,
                                                   "chunks": len(chunks), "file": path.name})
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
            report.failed += 1
            report.errors.append(f"{path.name}: {exc}")
            log.exception("failed to ingest transcript",
                          extra={"component": "ingest", "file": path.name})

    await db.commit()
    await refresh_index(db)
    log.info("ingestion finished", extra={"component": "ingest", **report.as_dict()})
    return report


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Lenny's Podcast transcripts.")
    parser.add_argument("--path", default=settings.transcripts_dir)
    parser.add_argument("--force", action="store_true",
                        help="re-embed documents even if unchanged")
    parser.add_argument("--prune-stale", action="store_true",
                        help="remove database documents absent from the transcript directory")
    args = parser.parse_args()

    configure_logging(settings.log_level, "console")
    await init_db()
    try:
        async with db_scope() as db:
            report = await ingest_path(db, args.path, force=args.force,
                                       prune_stale=args.prune_stale)
        print("\nIngestion report")
        print("----------------")
        for key, value in report.as_dict().items():
            print(f"  {key}: {value}")
    finally:
        await dispose_db()


if __name__ == "__main__":
    asyncio.run(_main())
