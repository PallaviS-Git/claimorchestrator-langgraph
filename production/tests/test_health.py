import pytest


def test_health_endpoint():
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("requests")

    from fastapi.testclient import TestClient

    from production.api.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

