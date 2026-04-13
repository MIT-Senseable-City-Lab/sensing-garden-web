import os
import re
import sys
from datetime import datetime, timedelta, timezone


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("API_BASE_URL", "http://localhost")
os.environ.setdefault("SENSING_GARDEN_API_KEY", "dummy-key")

from app import app
import app as dashboard_app


def _heartbeat(device_id: str, age: timedelta) -> dict:
    timestamp = datetime.now(timezone.utc) - age
    return {"device_id": device_id, "timestamp": timestamp.isoformat()}


def test_heartbeat_table_shows_full_device_id(monkeypatch):
    device_id = "sensing-garden-device-id-that-must-remain-visible"

    monkeypatch.setattr(dashboard_app.api, "fetch_heartbeats", lambda **_: {"items": [{"device_id": device_id}]})
    monkeypatch.setattr(dashboard_app, "_device_ids", lambda: [])

    with app.test_client() as client:
        response = client.get("/heartbeats")

    assert response.status_code == 200
    assert device_id.encode("utf-8") in response.data
    assert b"sensing-..." not in response.data


def test_heartbeats_page_links_to_device_history(monkeypatch):
    monkeypatch.setattr(dashboard_app.api, "fetch_heartbeats", lambda **_: {"items": [_heartbeat("FLIK2", timedelta(minutes=1))]})

    with app.test_client() as client:
        response = client.get("/heartbeats")

    assert response.status_code == 200
    assert b"Latest heartbeat per device" in response.data
    assert b'href="/heartbeats/FLIK2"' in response.data
    assert b'<select class="form-control form-control-sm" id="device_id"' not in response.data


def test_heartbeat_status_uses_five_minute_threshold(monkeypatch):
    monkeypatch.setattr(
        dashboard_app.api,
        "fetch_heartbeats",
        lambda **_: {"items": [_heartbeat("recent", timedelta(minutes=4)), _heartbeat("stale", timedelta(minutes=6))]},
    )

    with app.test_client() as client:
        response = client.get("/heartbeats")

    assert response.status_code == 200
    assert b'<span class="badge badge-online">online</span>' in response.data
    assert b'<span class="badge badge-offline">offline</span>' in response.data


def test_heartbeat_history_shows_device_summary_not_row_status(monkeypatch):
    captured = {}

    def fetch_heartbeats(**kwargs):
        captured.update(kwargs)
        return {"items": [_heartbeat("FLIK2", timedelta(minutes=1)), _heartbeat("FLIK2", timedelta(minutes=2))]}

    monkeypatch.setattr(dashboard_app.api, "fetch_heartbeats", fetch_heartbeats)

    with app.test_client() as client:
        response = client.get("/heartbeats/FLIK2")

    assert response.status_code == 200
    assert captured == {"device_id": "FLIK2"}
    assert b"Heartbeat History: FLIK2" in response.data
    assert b"All recorded heartbeats for FLIK2." in response.data
    assert b"Offline means no heartbeat in the last 5 minutes." in response.data
    header_text = b" ".join(re.findall(rb"<th[^>]*>\s*(.*?)\s*</th>", response.data, flags=re.DOTALL))
    assert b"Status" not in header_text.replace(b"DOT Status", b"")
    assert response.data.count(b'<span class="badge badge-online') == 1


def test_heartbeat_history_preserves_device_id_in_table_urls(monkeypatch):
    monkeypatch.setattr(
        dashboard_app.api,
        "fetch_heartbeats",
        lambda **_: {"items": [_heartbeat("FLIK2", timedelta(minutes=1)), _heartbeat("FLIK2", timedelta(minutes=2))]},
    )

    with app.test_client() as client:
        response = client.get("/heartbeats/FLIK2", query_string={"page": "2", "limit": "1"})

    assert response.status_code == 200
    assert b'href="/heartbeats/FLIK2"' in response.data
    assert b'href="/heartbeats/FLIK2?page=1&amp;limit=1"' in response.data
    assert b'href="/download_csv?table=heartbeats&amp;device_id=FLIK2"' in response.data


def test_heartbeat_history_csv_exports_selected_device(monkeypatch):
    captured = {}

    def fetch_heartbeats(**kwargs):
        captured.update(kwargs)
        return {"items": [_heartbeat("FLIK2", timedelta(minutes=1))]}

    monkeypatch.setattr(dashboard_app.api, "fetch_heartbeats", fetch_heartbeats)

    with app.test_client() as client:
        response = client.get("/download_csv", query_string={"table": "heartbeats", "device_id": "FLIK2"})

    assert response.status_code == 200
    assert captured == {"device_id": "FLIK2"}
    assert response.headers["Content-Type"].startswith("text/csv")
    assert b"device_id" in response.data
    assert b"FLIK2" in response.data
