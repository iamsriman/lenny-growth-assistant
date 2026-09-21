async def test_liveness_never_touches_dependencies(app_client):
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readiness_reports_each_dependency(app_client):
    resp = await app_client.get("/health/ready")
    assert resp.status_code == 200
    checks = resp.json()["checks"]
    assert checks["database"]["status"] == "ok"
    # Index is empty until ingestion runs -> degraded, not down.
    assert checks["knowledge_base"]["status"] == "empty"
    assert resp.json()["status"] == "degraded"


async def test_readiness_ok_once_ingested(seeded_client):
    body = (await seeded_client.get("/health/ready")).json()
    assert body["checks"]["knowledge_base"]["chunks"] > 0
    assert body["checks"]["knowledge_base"]["status"] == "ok"


async def test_request_id_is_echoed(app_client):
    resp = await app_client.get("/health", headers={"x-request-id": "abc123"})
    assert resp.headers["x-request-id"] == "abc123"
