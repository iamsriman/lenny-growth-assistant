from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# Tests are hermetic: SQLite, the deterministic hash embedder, and a stub chat
# provider. No network, no Ollama, no API keys.
os.environ.update({
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "EMBEDDING_PROVIDER": "hash",
    "LLM_PROVIDER": "ollama",
    "LLM_FALLBACK_PROVIDER": "",
    "ROUTER_MODE": "rules",
    "LOG_FORMAT": "console",
    "LOG_LEVEL": "WARNING",
    "TRANSCRIPTS_DIR": str(BACKEND_ROOT.parent / "data" / "transcripts"),
})

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import session as db_session  # noqa: E402
from app.llm import registry  # noqa: E402
from app.llm.base import ChatMessage, LLMProvider, ProviderStatus  # noqa: E402
from app.main import create_app  # noqa: E402
from app.rag import retriever  # noqa: E402


class StubProvider(LLMProvider):
    """Echoes a deterministic answer so assertions are about *our* plumbing."""

    name = "ollama"
    reply = "Grounded answer using [S1] and [S2]."
    calls: list[dict] = []

    def __init__(self, model: str = "stub-model"):
        super().__init__(model)

    async def generate(self, messages, *, system=None, temperature=0.3, max_tokens=2048):
        StubProvider.calls.append({"system": system, "messages": [m.content for m in messages]})
        return StubProvider.reply

    async def stream(self, messages, *, system=None, temperature=0.3, max_tokens=2048):
        StubProvider.calls.append({"system": system, "messages": [m.content for m in messages]})
        for word in StubProvider.reply.split(" "):
            yield word + " "

    async def status(self):
        return ProviderStatus(self.name, self.model, True, "stub")


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    StubProvider.calls = []
    StubProvider.reply = "Grounded answer using [S1] and [S2]."
    monkeypatch.setattr(registry, "build_provider",
                        lambda name, model=None: StubProvider(model or "stub-model"))
    monkeypatch.setattr(registry, "fallback_provider", lambda: None)
    yield
    registry.clear_overrides()


@pytest_asyncio.fixture
async def app_client():
    """A fresh in-memory database and index per test."""
    await db_session.dispose_db()
    registry.clear_overrides()
    retriever.get_index().__init__()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # lifespan is not run by ASGITransport, so set up explicitly.
        await db_session.init_db()
        yield client
    await db_session.dispose_db()


@pytest_asyncio.fixture
async def seeded_client(app_client):
    resp = await app_client.post("/api/knowledge/ingest", json={"path": os.environ["TRANSCRIPTS_DIR"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["chunks"] > 0
    return app_client


@pytest_asyncio.fixture
async def session_id(seeded_client):
    resp = await seeded_client.post("/api/sessions", json={"user_id": "tester"})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def chat_message():
    return ChatMessage
