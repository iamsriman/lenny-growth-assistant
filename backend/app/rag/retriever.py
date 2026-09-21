"""Retrieval.

Design note: the index is an in-process NumPy matrix rebuilt from Postgres at
startup, not pgvector. The corpus is a few thousand chunks, the deploy target
is an 8 GB laptop, and avoiding a Postgres extension keeps `docker compose up`
and Supabase both working unchanged. `VectorIndex` is the swap point if the
corpus outgrows memory — see architecture.md.

Scoring is hybrid: dense cosine catches paraphrase, BM25 catches the proper
nouns ("PLG", "Superhuman", "NPS") that embeddings routinely blur.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import TranscriptChunk, TranscriptDocument
from app.llm.registry import embed_texts

log = logging.getLogger("app.retrieval")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these",
    "those", "as", "at", "by", "from", "how", "what", "when", "why", "who", "do",
    "does", "did", "you", "your", "i", "we", "they", "he", "she", "about", "can",
    "should", "would", "could", "there", "their", "them", "so", "not", "no", "yes",
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) > 1 and t not in _STOPWORDS]


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    text: str
    title: str
    guest: str | None
    url: str | None
    speaker: str | None
    start_label: str | None
    ordinal: int
    synthetic: bool
    dense_score: float
    lexical_score: float
    score: float

    def as_citation(self, index: int) -> dict:
        return {
            "index": index,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "guest": self.guest,
            "url": self.url,
            "speaker": self.speaker,
            "timestamp": self.start_label,
            "synthetic": self.synthetic,
            "score": round(self.score, 4),
            "quote": self.text[:420].strip(),
        }


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    grounded: bool = False
    top_score: float = 0.0
    took_ms: float = 0.0
    degraded: bool = False
    note: str = ""

    def context_block(self) -> str:
        """The exact text handed to the model, with stable [S1..Sn] labels."""
        parts = []
        for i, c in enumerate(self.chunks, start=1):
            head = f"[S{i}] {c.title}"
            if c.guest:
                head += f" — guest: {c.guest}"
            if c.start_label:
                head += f" @ {c.start_label}"
            parts.append(f"{head}\n{c.text}")
        return "\n\n---\n\n".join(parts)

    def citations(self) -> list[dict]:
        return [c.as_citation(i) for i, c in enumerate(self.chunks, start=1)]


class VectorIndex:
    """In-process hybrid index. Rebuilt with `refresh()` after ingestion."""

    def __init__(self) -> None:
        self.chunk_ids: list[str] = []
        self.doc_ids: list[str] = []
        self.texts: list[str] = []
        self.meta: list[dict] = []
        self.matrix: np.ndarray | None = None
        self.embedding_model: str = ""
        self.doc_tokens: list[Counter] = []
        self.doc_len: np.ndarray | None = None
        self.avg_len: float = 1.0
        self.idf: dict[str, float] = {}
        self.built_at: float = 0.0

    @property
    def size(self) -> int:
        return len(self.chunk_ids)

    @property
    def ready(self) -> bool:
        return self.size > 0

    async def refresh(self, db: AsyncSession) -> int:
        started = time.perf_counter()
        rows = (
            await db.execute(
                select(TranscriptChunk)
                .options(selectinload(TranscriptChunk.document))
                .order_by(TranscriptChunk.document_id, TranscriptChunk.ordinal)
            )
        ).scalars().all()

        self.__init__()  # reset every field
        vectors: list[list[float]] = []
        for row in rows:
            if not row.embedding:
                continue
            doc: TranscriptDocument = row.document
            self.chunk_ids.append(row.id)
            self.doc_ids.append(row.document_id)
            self.texts.append(row.text)
            self.meta.append({
                "title": doc.title, "guest": doc.guest, "url": doc.url,
                "speaker": row.speaker, "start_label": row.start_label,
                "ordinal": row.ordinal, "synthetic": doc.synthetic,
            })
            vectors.append(row.embedding)
            self.embedding_model = row.embedding_model or self.embedding_model

        if vectors:
            mat = np.asarray(vectors, dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self.matrix = mat / norms
            self._build_lexical()

        self.built_at = time.time()
        took = (time.perf_counter() - started) * 1000
        log.info("index rebuilt", extra={"component": "retrieval", "chunks": self.size,
                                         "took_ms": round(took, 1),
                                         "embedding_model": self.embedding_model})
        return self.size

    def _build_lexical(self) -> None:
        self.doc_tokens = [Counter(tokenize(t)) for t in self.texts]
        self.doc_len = np.asarray([sum(c.values()) or 1 for c in self.doc_tokens],
                                  dtype=np.float32)
        self.avg_len = float(self.doc_len.mean())
        df: Counter = Counter()
        for counter in self.doc_tokens:
            df.update(counter.keys())
        n = len(self.doc_tokens)
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
                    for term, freq in df.items()}

    def bm25(self, query: str) -> np.ndarray:
        if not self.doc_tokens or self.doc_len is None:
            return np.zeros(self.size, dtype=np.float32)
        k1, b = 1.5, 0.75
        scores = np.zeros(self.size, dtype=np.float32)
        ceiling = 0.0
        for term in tokenize(query):
            idf = self.idf.get(term)
            if idf is None:
                # Term absent from the whole corpus: it contributes nothing and
                # it does not lower the ceiling either, so an off-topic query
                # scores near zero rather than being renormalised up to 1.0.
                continue
            tf = np.asarray([c.get(term, 0) for c in self.doc_tokens], dtype=np.float32)
            denom = tf + k1 * (1 - b + b * self.doc_len / self.avg_len)
            scores += idf * (tf * (k1 + 1)) / np.maximum(denom, 1e-6)
            ceiling += idf * (k1 + 1)
        if ceiling <= 0:
            return scores
        # Normalise against the maximum *achievable* score for this query, so
        # the value is comparable across queries and can drive a threshold.
        return np.clip(scores / ceiling, 0.0, 1.0)


_index = VectorIndex()


def get_index() -> VectorIndex:
    return _index


async def refresh_index(db: AsyncSession) -> int:
    return await _index.refresh(db)


async def retrieve(
    query: str,
    *,
    top_k: int | None = None,
    index: VectorIndex | None = None,
) -> RetrievalResult:
    idx = index or _index
    started = time.perf_counter()
    top_k = top_k or settings.retrieval_top_k

    if not idx.ready:
        return RetrievalResult(
            grounded=False, took_ms=0.0,
            note="The knowledge base is empty. Run the ingestion command first.",
        )

    vectors, model_label = await embed_texts([query])
    degraded = model_label.startswith("hash") and not idx.embedding_model.startswith("hash")
    q = np.asarray(vectors[0], dtype=np.float32)

    dense = np.zeros(idx.size, dtype=np.float32)
    if idx.matrix is not None and q.shape[0] == idx.matrix.shape[1]:
        norm = np.linalg.norm(q) or 1.0
        dense = idx.matrix @ (q / norm)
    else:
        # Dimension mismatch = the index and the query were embedded by
        # different models. Lexical still works, so degrade rather than fail.
        degraded = True

    lexical = idx.bm25(query)
    combined = 0.62 * np.clip(dense, 0, None) + 0.38 * lexical

    candidate_k = min(settings.retrieval_candidate_k, idx.size)
    order = np.argsort(-combined)[:candidate_k]

    picked: list[RetrievedChunk] = []
    per_doc: Counter = Counter()
    for pos in order:
        doc_id = idx.doc_ids[pos]
        if per_doc[doc_id] >= settings.max_chunks_per_episode:
            continue
        per_doc[doc_id] += 1
        meta = idx.meta[pos]
        picked.append(RetrievedChunk(
            chunk_id=idx.chunk_ids[pos], document_id=doc_id, text=idx.texts[pos],
            title=meta["title"], guest=meta["guest"], url=meta["url"],
            speaker=meta["speaker"], start_label=meta["start_label"],
            ordinal=meta["ordinal"], synthetic=meta["synthetic"],
            dense_score=float(dense[pos]), lexical_score=float(lexical[pos]),
            score=float(combined[pos]),
        ))
        if len(picked) >= top_k:
            break

    top = picked[0].score if picked else 0.0
    threshold = (settings.retrieval_min_score_fallback
                 if idx.embedding_model.startswith("hash")
                 else settings.retrieval_min_score)
    grounded = top >= threshold
    result = RetrievalResult(
        chunks=picked if grounded else picked[:2],
        grounded=grounded,
        top_score=top,
        took_ms=(time.perf_counter() - started) * 1000,
        degraded=degraded,
        note="" if grounded else
             "No transcript passage cleared the grounding threshold for this question.",
    )
    log.info("retrieval complete", extra={
        "component": "retrieval", "query_chars": len(query), "hits": len(result.chunks),
        "top_score": round(top, 4), "threshold": threshold,
        "grounded": grounded, "degraded": degraded,
        "took_ms": round(result.took_ms, 1),
    })
    return result
