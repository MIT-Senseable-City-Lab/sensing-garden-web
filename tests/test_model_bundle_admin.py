import io
import os
import sys


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault("API_BASE_URL", "http://localhost")
os.environ.setdefault("SENSING_GARDEN_API_KEY", "dummy-key")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "dummy-aws-key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "dummy-aws-secret")
os.environ.setdefault("AWS_REGION", "us-east-1")

from app import app
import app as dashboard_app


FAKE_MODELS_RESPONSE = {
    "items": [
        {
            "id": "bundle-model",
            "name": "Bundle Model",
            "version": "1.0.0",
            "description": "test",
            "metadata": {
                "bundle": {
                    "bundle_uploaded_at": "2026-03-18T00:00:00Z",
                    "model_sha256": "abc123abc123abc123",
                    "labels_sha256": "def456def456def456",
                }
            },
        }
    ]
}


def test_models_page_shows_bundle_status(monkeypatch):
    monkeypatch.setattr(dashboard_app.api, "fetch_models", lambda **kw: FAKE_MODELS_RESPONSE)

    with app.test_client() as client:
        response = client.get("/view_table/models")

    assert response.status_code == 200
    assert b"Bundle Model" in response.data
    assert b"Ready" in response.data


def test_add_model_uploads_bundle_and_creates_record(monkeypatch):
    calls = {}

    def fake_upload(model_id, model_file, labels_file):
        calls["upload"] = {
            "model_id": model_id,
            "model_filename": model_file.filename,
            "labels_filename": labels_file.filename,
        }
        return {
            "bundle_uploaded_at": "2026-03-18T00:00:00Z",
            "model_id": model_id,
            "model_sha256": "abc123",
            "labels_sha256": "def456",
            "model_etag": "etag-a",
            "labels_etag": "etag-b",
            "bundle_key_model": f"{model_id}/model.hef",
            "bundle_key_labels": f"{model_id}/labels.txt",
        }

    def fake_create(model_data):
        calls["create"] = model_data
        return {"ok": True}

    monkeypatch.setattr(dashboard_app, "upload_model_bundle", fake_upload)
    monkeypatch.setattr(dashboard_app, "create_model_record", fake_create)

    with app.test_client() as client:
        response = client.post(
            "/add_model",
            data={
                "model_id": "bundle-model",
                "name": "Bundle Model",
                "version": "1.0.0",
                "description": "test",
                "metadata": '{"type":"edge26-classifier"}',
                "model_file": (io.BytesIO(b"hef"), "uploaded.hef"),
                "labels_file": (io.BytesIO(b"labels"), "uploaded-labels.txt"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 302
    assert calls["upload"]["model_id"] == "bundle-model"
    assert calls["create"]["metadata"]["type"] == "edge26-classifier"
    assert calls["create"]["metadata"]["bundle"]["model_sha256"] == "abc123"


def test_delete_model_route_removes_bundle_then_record(monkeypatch):
    call_order = []

    monkeypatch.setattr(dashboard_app, "delete_model_bundle", lambda model_id: call_order.append(("bundle", model_id)))
    monkeypatch.setattr(dashboard_app, "delete_model_record", lambda model_id: call_order.append(("record", model_id)))

    with app.test_client() as client:
        response = client.post("/models/bundle-model/delete")

    assert response.status_code == 302
    assert call_order == [("bundle", "bundle-model"), ("record", "bundle-model")]
