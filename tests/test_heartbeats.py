import os
import sys


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("API_BASE_URL", "http://localhost")
os.environ.setdefault("SENSING_GARDEN_API_KEY", "dummy-key")

from app import app
import app as dashboard_app


def test_heartbeat_table_shows_full_device_id(monkeypatch):
    device_id = "sensing-garden-device-id-that-must-remain-visible"

    monkeypatch.setattr(dashboard_app.api, "fetch_heartbeats", lambda **_: {"items": [{"device_id": device_id}]})
    monkeypatch.setattr(dashboard_app, "_device_ids", lambda: [])

    with app.test_client() as client:
        response = client.get("/heartbeats")

    assert response.status_code == 200
    assert device_id.encode("utf-8") in response.data
    assert b"sensing-..." not in response.data
