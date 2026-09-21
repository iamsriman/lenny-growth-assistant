import os
from pathlib import Path

from app.rag.chunker import chunk_turns, discover_transcripts, parse_file
from app.rag.retriever import retrieve


def test_front_matter_and_speaker_turns_are_parsed():
    path = Path(os.environ["TRANSCRIPTS_DIR"]) / "sample-growth-loops.md"
    parsed = parse_file(path)
    assert parsed.guest == "Priya Raman"
    assert parsed.synthetic is True
    assert parsed.url
    speakers = {t.speaker for t in parsed.turns if t.speaker}
    assert "Priya Raman" in speakers and "Host" in speakers


def test_chunking_respects_target_size_and_overlaps():
    path = Path(os.environ["TRANSCRIPTS_DIR"]) / "sample-plg-pricing.md"
    chunks = chunk_turns(parse_file(path).turns, target_chars=600, overlap_chars=100)
    assert len(chunks) > 2
    assert all(len(c.text) <= 1100 for c in chunks)
    assert all(c.text.strip() for c in chunks)
    assert [c.ordinal for c in chunks] == sorted(c.ordinal for c in chunks)


def test_discovery_ignores_readme():
    files = discover_transcripts(os.environ["TRANSCRIPTS_DIR"])
    assert files
    assert all(f.name.lower() != "readme.md" for f in files)


async def test_ingest_is_idempotent(app_client):
    first = (await app_client.post("/api/knowledge/ingest", json={})).json()
    second = (await app_client.post("/api/knowledge/ingest", json={})).json()
    assert first["ingested"] > 0
    assert second["ingested"] == 0
    assert second["skipped"] == first["ingested"]


async def test_retrieval_returns_grounded_hits(seeded_client):
    result = await retrieve("what value metric should a product led company charge on")
    assert result.grounded
    assert result.chunks
    assert "[S1]" in result.context_block()
    top = result.citations()[0]
    assert top["title"]
    assert top["synthetic"] is True


async def test_retrieval_diversifies_across_episodes(seeded_client):
    result = await retrieve(
        "how do teams measure activation retention and the growth loops behind them",
        top_k=6)
    docs = [c.document_id for c in result.chunks]
    assert len(set(docs)) > 1
    for doc in set(docs):
        assert docs.count(doc) <= 2


async def test_off_topic_question_is_not_grounded(seeded_client):
    result = await retrieve("what is the melting point of tungsten carbide in kelvin")
    assert result.grounded is False
    assert result.note


async def test_search_endpoint_exposes_scores(seeded_client):
    body = (await seeded_client.get("/api/knowledge/search",
                                    params={"q": "growth loop cycle time"})).json()
    assert body["grounded"] is True
    assert body["results"][0]["score"] > 0
    assert body["results"][0]["quote"]


async def test_documents_endpoint_flags_synthetic(seeded_client):
    body = (await seeded_client.get("/api/knowledge/documents")).json()
    assert body["total_documents"] >= 4
    assert body["synthetic_present"] is True
