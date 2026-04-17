import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault("API_BASE_URL", "http://localhost")
os.environ.setdefault("SENSING_GARDEN_API_KEY", "dummy-key")

from app import app
import app as dashboard_app


class FakeActivityTable:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def put_item(self, Item: dict[str, Any]) -> None:
        self.items.append(Item)


class FakeS3:
    def __init__(self) -> None:
        self.presigned: list[dict[str, Any]] = []
        self.objects: dict[str, bytes] = {
            "v1/device-1/results.json": json.dumps({"device": "device-1", "tracks": [2]}).encode("utf-8"),
            "v1/device-1/bad.json": b"{bad",
        }

    def list_objects_v2(self, **params: Any) -> dict[str, Any]:
        assert params["Bucket"] == dashboard_app.OUTPUT_BUCKET
        return {
            "CommonPrefixes": [{"Prefix": "v1/device-1/logs/"}],
            "Contents": [
                {
                    "Key": "v1/device-1/frame.jpg",
                    "Size": 1200,
                    "LastModified": datetime(2026, 4, 12, tzinfo=timezone.utc),
                },
                {
                    "Key": "v1/device-1/results.json",
                    "Size": 42,
                    "LastModified": datetime(2026, 4, 12, tzinfo=timezone.utc),
                }
            ],
        }

    def generate_presigned_url(self, operation: str, Params: dict[str, str], ExpiresIn: int) -> str:
        self.presigned.append({"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn})
        return "https://example.test/read"

    def get_object(self, Bucket: str, Key: str) -> dict[str, "FakeBody"]:
        assert Bucket == dashboard_app.OUTPUT_BUCKET
        return {"Body": FakeBody(self.objects[Key])}


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


def test_s3_browser_lists_output_bucket(monkeypatch: Any) -> None:
    monkeypatch.setattr(dashboard_app, "get_s3_client", lambda: FakeS3())
    monkeypatch.setattr(dashboard_app, "get_activity_table", lambda: FakeActivityTable())

    with app.test_client() as client:
        response = client.get("/s3?prefix=v1/device-1/")

    assert response.status_code == 200
    assert b"logs/" in response.data
    assert b"frame.jpg" in response.data
    assert b"results.json" in response.data
    assert b'data-key="v1/device-1/frame.jpg" data-title="frame.jpg">View' in response.data
    assert b'data-key="v1/device-1/results.json" data-title="results.json">View</button>' not in response.data
    assert b'data-key="v1/device-1/results.json" data-title="results.json">View JSON' in response.data
    assert b'data-key="v1/device-1/frame.jpg" data-title="frame.jpg">View JSON' not in response.data


def test_s3_open_is_read_only_and_audited(monkeypatch: Any) -> None:
    fake_s3 = FakeS3()
    fake_table = FakeActivityTable()
    monkeypatch.setattr(dashboard_app, "get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(dashboard_app, "get_activity_table", lambda: fake_table)

    with app.test_client() as client:
        response = client.get("/api/s3/open?key=v1/device-1/results.json")

    assert response.status_code == 200
    assert response.get_json()["url"] == "https://example.test/read"
    assert fake_s3.presigned[0]["operation"] == "get_object"
    assert fake_s3.presigned[0]["Params"]["Key"] == "v1/device-1/results.json"
    assert fake_table.items[0]["event_type"] == "s3_open"


def test_s3_open_rejects_invalid_key(monkeypatch: Any) -> None:
    monkeypatch.setattr(dashboard_app, "get_s3_client", lambda: FakeS3())

    with app.test_client() as client:
        response = client.get("/api/s3/open?key=../secret")

    assert response.status_code == 400


def test_s3_json_returns_pretty_json_and_is_audited(monkeypatch: Any) -> None:
    fake_table = FakeActivityTable()
    monkeypatch.setattr(dashboard_app, "get_s3_client", lambda: FakeS3())
    monkeypatch.setattr(dashboard_app, "get_activity_table", lambda: fake_table)

    with app.test_client() as client:
        response = client.get("/api/s3/json?key=v1/device-1/results.json")

    payload = response.get_json()
    assert payload is not None
    assert response.status_code == 200
    assert payload["key"] == "v1/device-1/results.json"
    assert payload["json"] == '{\n  "device": "device-1",\n  "tracks": [\n    2\n  ]\n}'
    assert fake_table.items[0]["event_type"] == "s3_open"


def test_s3_json_rejects_invalid_key(monkeypatch: Any) -> None:
    monkeypatch.setattr(dashboard_app, "get_s3_client", lambda: FakeS3())

    with app.test_client() as client:
        response = client.get("/api/s3/json?key=../secret.json")

    assert response.status_code == 400


def test_s3_json_rejects_non_json_key(monkeypatch: Any) -> None:
    monkeypatch.setattr(dashboard_app, "get_s3_client", lambda: FakeS3())

    with app.test_client() as client:
        response = client.get("/api/s3/json?key=v1/device-1/frame.jpg")

    assert response.status_code == 400


def test_s3_json_rejects_malformed_json(monkeypatch: Any) -> None:
    monkeypatch.setattr(dashboard_app, "get_s3_client", lambda: FakeS3())

    with app.test_client() as client:
        response = client.get("/api/s3/json?key=v1/device-1/bad.json")

    assert response.status_code == 400


def test_activity_api_returns_merged_rows(monkeypatch):
    monkeypatch.setattr(
        dashboard_app,
        "merged_activity_rows",
        lambda source, device_id, query, limit: [{"source": source or "dashboard", "message": query or "ok"}],
    )

    with app.test_client() as client:
        response = client.get("/api/admin/activity?source=dashboard&q=opened")

    assert response.status_code == 200
    assert response.get_json()["items"][0]["message"] == "opened"


def test_admin_logs_page_includes_live_polling_controls():
    with app.test_client() as client:
        response = client.get("/admin/logs")

    assert response.status_code == 200
    assert b'id="live-logs"' in response.data
    assert b"var LIVE_POLL_MS = 2000;" in response.data
    assert b"var ERROR_LEVELS = ['ERROR', 'CRITICAL', 'FATAL'];" in response.data
    assert b"Number(item.status_code) >= 400" in response.data
    assert b'class=\"table-danger\"' in response.data
    assert b"setLiveEnabled(e.target.checked)" in response.data
    assert b"/api/admin/activity?" in response.data
