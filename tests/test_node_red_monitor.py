from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.main import app
from backend.realtime.node_red_monitor import node_red_monitor


def test_node_red_ingest_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "node_red_monitor_token", "test-secret")
    with TestClient(app) as client:
        denied = client.post("/api/v1/node-red/events", json={"event": "heartbeat"})
        assert denied.status_code == 401
        accepted = client.post(
            "/api/v1/node-red/events",
            headers={"X-Node-RED-Token": "test-secret"},
            json={"event": "heartbeat", "message": "test heartbeat"},
        )
        assert accepted.status_code == 202
        assert accepted.json()["ok"] is True
        assert accepted.json()["status"]["online"] is True


def test_node_red_status_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/node-red/status")
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_node_red_websocket_sends_snapshot():
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/node-red/ws") as websocket:
            message = websocket.receive_json()
            assert message["type"] == "node_red_snapshot"
            assert "status" in message
            assert isinstance(message["events"], list)


def test_node_red_event_is_broadcast_to_websocket(monkeypatch):
    monkeypatch.setattr(settings, "node_red_monitor_token", "broadcast-secret")
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/node-red/ws") as websocket:
            websocket.receive_json()  # snapshot inicial
            response = client.post(
                "/api/v1/node-red/events",
                headers={"X-Node-RED-Token": "broadcast-secret"},
                json={"event": "node_error", "level": "error", "message": "test error"},
            )
            assert response.status_code == 202
            message = websocket.receive_json()
            assert message["type"] == "node_red_event"
            assert message["event"]["event"] == "node_error"
            assert message["event"]["message"] == "test error"


def test_node_red_ingest_is_disabled_without_shared_secret(monkeypatch):
    monkeypatch.setattr(settings, "node_red_monitor_token", "")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/node-red/events",
            headers={"X-Node-RED-Token": "anything"},
            json={"event": "heartbeat"},
        )
        assert response.status_code == 503


def test_dashboard_exposes_node_red_monitor_contract():
    from pathlib import Path

    from backend.core.config import settings

    html = (Path(settings.frontend_dir) / "index.html").read_text(encoding="utf-8")
    script = (Path(settings.frontend_dir) / "app.js").read_text(encoding="utf-8")
    assert 'id="view-node-red"' in html
    assert "/api/v1/node-red/ws" in script
    assert "/api/v1/node-red/status" in script
