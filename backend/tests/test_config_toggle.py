async def test_config_exposes_active_provider(app_client):
    body = (await app_client.get("/api/config")).json()
    assert body["active"]["provider"] == "ollama"
    assert "anthropic" in body["providers"]
    assert body["embedding_provider"] == "hash"


async def test_toggle_switches_provider_without_restart(app_client):
    patched = (await app_client.patch("/api/config",
                                      json={"provider": "anthropic"})).json()
    assert patched["active"]["provider"] == "anthropic"
    assert (await app_client.get("/api/config")).json()["active"]["provider"] == "anthropic"


async def test_toggle_switches_to_groq(app_client):
    patched = (await app_client.patch("/api/config",
                                      json={"provider": "groq"})).json()
    assert patched["active"]["provider"] == "groq"
    assert patched["active"]["model"] == "openai/gpt-oss-120b"


async def test_toggle_records_provider_on_new_sessions(seeded_client):
    await seeded_client.patch("/api/config", json={"provider": "openai",
                                                   "model": "gpt-4o-mini"})
    sid = (await seeded_client.post("/api/sessions", json={})).json()["id"]
    body = (await seeded_client.get(f"/api/sessions/{sid}")).json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"


async def test_unknown_provider_is_rejected(app_client):
    assert (await app_client.patch("/api/config",
                                   json={"provider": "llamafile"})).status_code == 422


async def test_clearing_overrides_restores_default(app_client):
    await app_client.patch("/api/config", json={"provider": "openai"})
    restored = (await app_client.patch("/api/config", json={})).json()
    assert restored["active"]["provider"] == "ollama"
