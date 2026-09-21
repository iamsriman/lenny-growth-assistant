async def test_create_and_fetch_session(app_client):
    created = await app_client.post("/api/sessions", json={"title": "Growth Q3",
                                                           "user_id": "u1"})
    assert created.status_code == 201
    sid = created.json()["id"]

    got = await app_client.get(f"/api/sessions/{sid}")
    assert got.status_code == 200
    assert got.json()["title"] == "Growth Q3"
    assert got.json()["messages"] == []


async def test_sessions_are_isolated(seeded_client):
    a = (await seeded_client.post("/api/sessions", json={})).json()["id"]
    b = (await seeded_client.post("/api/sessions", json={})).json()["id"]

    await seeded_client.post("/api/chat", json={"session_id": a,
                                                "message": "What predicts retention?"})
    detail_a = (await seeded_client.get(f"/api/sessions/{a}")).json()
    detail_b = (await seeded_client.get(f"/api/sessions/{b}")).json()

    assert len(detail_a["messages"]) == 2
    assert detail_b["messages"] == []


async def test_missing_session_returns_structured_error(app_client):
    resp = await app_client.get("/api/sessions/does-not-exist")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "session_not_found"
    assert error["request_id"]


async def test_title_is_derived_from_first_message(session_id, seeded_client):
    await seeded_client.post("/api/chat", json={"session_id": session_id,
                                                "message": "How do growth loops decay?"})
    body = (await seeded_client.get(f"/api/sessions/{session_id}")).json()
    assert body["title"].startswith("How do growth loops")


async def test_delete_cascades(session_id, seeded_client):
    await seeded_client.post("/api/chat", json={"session_id": session_id,
                                                "message": "What is activation?"})
    assert (await seeded_client.delete(f"/api/sessions/{session_id}")).status_code == 204
    assert (await seeded_client.get(f"/api/sessions/{session_id}")).status_code == 404


async def test_validation_error_shape(app_client):
    resp = await app_client.post("/api/chat", json={"session_id": "x", "message": ""})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
