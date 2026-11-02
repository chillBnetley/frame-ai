from __future__ import annotations

from app.services.image_service import StorageStatus


def test_health_reports_ready(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status": "ok",
        "service": "FRAME AI API",
        "version": "0.1.0",
        "storage": {"ok": True, "writable": True},
    }
    assert set(payload["storage"]) == {"ok", "writable"}
    assert response.headers["x-request-id"]


def test_health_reports_storage_not_writable(client, monkeypatch):
    service = client.app.state.image_service
    monkeypatch.setattr(
        service,
        "storage_status",
        lambda: StorageStatus(ok=False, writable=False),
    )

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["storage"] == {"ok": False, "writable": False}


def test_health_request_id_is_echoed_when_safe(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "client-test-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "client-test-123"


def test_health_rejects_unsafe_request_id(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad value"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad value"


def test_unknown_route_uses_error_contract(client):
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == "not_found"
