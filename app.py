import csv
import hmac
import hashlib
import io
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Union
from urllib.parse import urlparse

import boto3
import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, make_response, redirect, render_template, request, session, url_for

from activity import (
    ActivityEvent,
    ActivityEventType,
    ActivitySource,
    bugcam_log_events,
    event_message,
    list_activity_events,
    record_activity_event,
    s3_object_event,
    utc_now,
)


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "sensing-garden-dashboard-dev")
app.config["SESSION_COOKIE_NAME"] = "sg_auth"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

API_BASE_URL = os.getenv("API_BASE_URL", "https://api.sensinggarden.com/v1")
API_KEY = os.getenv("SENSING_GARDEN_API_KEY", "")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
MODELS_BUCKET = os.getenv("MODELS_BUCKET", "scl-sensing-garden-models")
VIDEOS_BUCKET = os.getenv("VIDEOS_BUCKET", "scl-sensing-garden-videos")
IMAGES_BUCKET = os.getenv("IMAGES_BUCKET", "scl-sensing-garden-images")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "scl-sensing-garden")
ACTIVITY_EVENTS_TABLE = os.getenv("ACTIVITY_EVENTS_TABLE", "sensing-garden-activity-events")
MODEL_FILENAME = "model.hef"
LABELS_FILENAME = "labels.txt"
HEARTBEAT_ONLINE_THRESHOLD = timedelta(hours=2)
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200
FETCH_ALL_PAGE_LIMIT = 500
WEB_READ_ONLY = os.getenv("WEB_READ_ONLY", "true").lower() in {"1", "true", "yes", "on"}
EXPORTABLE_API_TABLES = {"classifications", "devices", "videos", "environment"}
S3_IMAGE_EXTENSIONS: FrozenSet[str] = frozenset({
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
})


@dataclass(frozen=True)
class TableColumn:
    key: str
    label: str
    sortable: bool = True
    kind: str = "text"
    url_key: Optional[str] = None
    link_endpoint: Optional[str] = None
    link_param: Optional[str] = None


class ApiClient:
    """Minimal HTTP client for the Sensing Garden REST API."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        path = endpoint.lstrip("/")
        try:
            response = requests.request(
                method,
                f"{self.base_url}/{path}",
                params=params,
                json=body,
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=30,
            )
        except requests.RequestException:
            record_dashboard_api_request(method, path, 0)
            raise
        record_dashboard_api_request(method, path, response.status_code)
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected response shape from {endpoint}")
        return payload

    def _list_params(
        self,
        *,
        device_id: Optional[str] = None,
        limit: Optional[int] = None,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if device_id:
            params["device_id"] = device_id
        if limit:
            params["limit"] = limit
        if next_token:
            params["next_token"] = next_token
        if sort_by:
            params["sort_by"] = sort_by
        if sort_desc:
            params["sort_desc"] = "true"
        if extra:
            for key, value in extra.items():
                if value not in (None, ""):
                    params[key] = value
        return params

    def fetch_tracks(
        self,
        *,
        device_id: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "tracks",
            params=self._list_params(
                device_id=device_id,
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc,
            ),
        )

    def count_tracks(self, device_id: Optional[str] = None) -> int:
        return int(self._request("GET", "tracks/count", params=self._list_params(device_id=device_id)).get("count", 0))

    def get_track(self, track_id: str) -> Dict[str, Any]:
        return self._request("GET", f"tracks/{track_id}").get("track", {})

    def fetch_classifications(
        self,
        *,
        device_id: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "classifications",
            params=self._list_params(
                device_id=device_id,
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc,
            ),
        )

    def count_classifications(self, device_id: Optional[str] = None) -> int:
        return int(
            self._request("GET", "classifications/count", params=self._list_params(device_id=device_id)).get("count", 0)
        )

    def fetch_devices(
        self,
        *,
        device_id: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = False,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "devices",
            params=self._list_params(
                device_id=device_id,
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc,
            ),
        )

    def fetch_models(
        self,
        *,
        limit: int = DEFAULT_PAGE_LIMIT,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "models",
            params=self._list_params(limit=limit, next_token=next_token, sort_by=sort_by, sort_desc=sort_desc),
        )

    def count_models(self) -> int:
        return int(self._request("GET", "models/count").get("count", 0))

    def fetch_videos(
        self,
        *,
        device_id: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "videos",
            params=self._list_params(
                device_id=device_id,
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc,
            ),
        )

    def count_videos(self, device_id: Optional[str] = None) -> int:
        return int(self._request("GET", "videos/count", params=self._list_params(device_id=device_id)).get("count", 0))

    def fetch_environment(
        self,
        *,
        device_id: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "environment",
            params=self._list_params(
                device_id=device_id,
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc,
            ),
        )

    def count_environment(self, device_id: Optional[str] = None) -> int:
        return int(
            self._request("GET", "environment/count", params=self._list_params(device_id=device_id)).get("count", 0)
        )

    def fetch_heartbeats(self, *, device_id: str = "") -> Dict[str, Any]:
        params = {}
        if device_id:
            params["device_id"] = device_id
        return self._request("GET", "heartbeats", params=params)

    def fetch_deployments(
        self,
        *,
        limit: int = DEFAULT_PAGE_LIMIT,
        next_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        payload = self._request(
            "GET",
            "deployments",
            params=self._list_params(limit=limit, next_token=next_token, sort_by=sort_by, sort_desc=sort_desc),
        )
        return {
            "items": payload.get("deployments", []),
            "count": payload.get("count", 0),
            "next_token": payload.get("next_token"),
        }

    def get_deployment(self, deployment_id: str) -> Dict[str, Any]:
        return self._request("GET", f"deployments/{deployment_id}")

    def delete_device(self, device_id: str) -> Dict[str, Any]:
        return self._request("DELETE", "devices", body={"device_id": device_id})

    def create_model(self, model_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "models", body=model_data)

    def delete_model(self, model_id: str) -> Dict[str, Any]:
        return self._request("DELETE", "models", body={"model_id": model_id})


api = ApiClient(API_BASE_URL, API_KEY)


def _dashboard_auth_enabled() -> bool:
    return bool(DASHBOARD_PASSWORD)


def _dashboard_auth_token() -> str:
    return hashlib.sha256(DASHBOARD_PASSWORD.encode("utf-8")).hexdigest()


def _dashboard_is_authenticated() -> bool:
    if not _dashboard_auth_enabled():
        return True
    token = session.get("dashboard_auth")
    return isinstance(token, str) and hmac.compare_digest(token, _dashboard_auth_token())


@app.before_request
def require_dashboard_password() -> Optional[Response]:
    if not _dashboard_auth_enabled():
        return None
    if request.endpoint in {"login", "health_check", "static"}:
        return None
    if _dashboard_is_authenticated():
        return None
    next_url = request.full_path if request.query_string else request.path
    return redirect(url_for("login", next=next_url))


TRACK_COLUMNS = [
    TableColumn("track_id", "Track ID", link_endpoint="view_track_detail", link_param="track_id"),
    TableColumn("device_id", "Device ID"),
    TableColumn("species", "Species"),
    TableColumn("family_confidence", "Family Confidence"),
    TableColumn("genus_confidence", "Genus Confidence"),
    TableColumn("species_confidence", "Species Confidence"),
    TableColumn("num_detections", "Detections"),
    TableColumn("timestamp", "Timestamp"),
    TableColumn("composite_preview", "Composite", sortable=False, kind="image", url_key="composite_url"),
]

CLASSIFICATION_COLUMNS = [
    TableColumn("device_id", "Device ID"),
    TableColumn("timestamp", "Timestamp"),
    TableColumn("track_id", "Track ID", link_endpoint="view_track_detail", link_param="track_id"),
    TableColumn("family", "Family"),
    TableColumn("genus", "Genus"),
    TableColumn("species", "Species"),
    TableColumn("family_confidence", "Family Confidence"),
    TableColumn("genus_confidence", "Genus Confidence"),
    TableColumn("species_confidence", "Species Confidence"),
    TableColumn("frame_number", "Frame"),
    TableColumn("bounding_box", "Bounding Box", sortable=False, kind="json"),
    TableColumn("image_key", "Image Key"),
    TableColumn("image_preview", "Crop", sortable=False, kind="image", url_key="image_url"),
    TableColumn("model_id", "Model ID"),
]

DEVICE_COLUMNS = [
    TableColumn("device_id", "Device ID"),
    TableColumn("parent_device_id", "Parent Device ID"),
    TableColumn("device_type", "Type", sortable=False, kind="badge"),
    TableColumn("created", "Created"),
]

HEARTBEAT_COLUMNS = [
    TableColumn("device_id", "Device ID", sortable=False),
    TableColumn("status", "Status", sortable=False, kind="badge"),
    TableColumn("timestamp", "Timestamp", sortable=False),
    TableColumn("age", "Age", sortable=False),
    TableColumn("cpu_temperature_celsius", "CPU Temp", sortable=False),
    TableColumn("storage_free_bytes", "Free Bytes", sortable=False),
    TableColumn("storage_total_bytes", "Total Bytes", sortable=False),
    TableColumn("uptime_seconds", "Uptime (s)", sortable=False),
    TableColumn("dot_status", "DOT Status", sortable=False, kind="json"),
]

VIDEO_COLUMNS = [
    TableColumn("device_id", "Device ID"),
    TableColumn("timestamp", "Timestamp"),
    TableColumn("video_key", "Video Key"),
    TableColumn("video_player", "Video", sortable=False, kind="video", url_key="video_url"),
    TableColumn("s3_prefix", "S3 Prefix"),
    TableColumn("fps", "FPS"),
    TableColumn("total_frames", "Total Frames"),
    TableColumn("duration_seconds", "Duration (s)"),
]

DEPLOYMENT_COLUMNS = [
    TableColumn("deployment_id", "Deployment ID"),
    TableColumn("name", "Name"),
    TableColumn("description", "Description"),
    TableColumn("start_time", "Start Time"),
    TableColumn("end_time", "End Time"),
    TableColumn("model_id", "Model ID"),
    TableColumn("location_name", "Location Name"),
    TableColumn("location", "Location", sortable=False, kind="json"),
    TableColumn("image_key", "Image Key"),
    TableColumn("image_preview", "Image", sortable=False, kind="image", url_key="image_url"),
    TableColumn("linked_devices", "Devices", sortable=False, kind="list"),
]

ENVIRONMENT_COLUMNS = [
    TableColumn("device_id", "Device ID"),
    TableColumn("timestamp", "Timestamp"),
    TableColumn("temperature", "Temperature"),
    TableColumn("humidity", "Humidity"),
    TableColumn("pm1p0", "PM1.0"),
    TableColumn("pm2p5", "PM2.5"),
    TableColumn("pm4p0", "PM4.0"),
    TableColumn("pm10p0", "PM10.0"),
    TableColumn("voc_index", "VOC"),
    TableColumn("nox_index", "NOx"),
    TableColumn("light_level", "Light"),
    TableColumn("pressure", "Pressure"),
    TableColumn("location", "Location", sortable=False, kind="json"),
]

MODEL_COLUMNS = [
    TableColumn("bundle_name", "Bundle"),
    TableColumn("files_present", "Files Present", sortable=False),
    TableColumn("model_size_bytes", "model.hef"),
    TableColumn("labels_size_bytes", "labels.txt"),
    TableColumn("last_modified_time", "Last Modified"),
]


@app.context_processor
def inject_web_mode() -> Dict[str, Any]:
    return {"web_read_only": WEB_READ_ONLY}


def _aws_client_kwargs() -> Dict[str, str]:
    client_kwargs: Dict[str, str] = {}
    if os.getenv("AWS_ACCESS_KEY_ID"):
        client_kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID", "")
    if os.getenv("AWS_SECRET_ACCESS_KEY"):
        client_kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if os.getenv("AWS_SESSION_TOKEN"):
        client_kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN", "")
    if os.getenv("AWS_REGION"):
        client_kwargs["region_name"] = os.getenv("AWS_REGION", "")
    return client_kwargs


def get_s3_client() -> Any:
    return boto3.client("s3", **_aws_client_kwargs())


def get_dynamodb_resource() -> Any:
    return boto3.resource("dynamodb", **_aws_client_kwargs())


def get_activity_table() -> Any:
    return get_dynamodb_resource().Table(ACTIVITY_EVENTS_TABLE)


def get_models_s3_client() -> Any:
    return get_s3_client()


def record_dashboard_api_request(method: str, path: str, status_code: int) -> None:
    event = ActivityEvent(
        timestamp=utc_now(),
        source=ActivitySource.DASHBOARD,
        event_type=ActivityEventType.API_REQUEST,
        actor_type="dashboard",
        method=method,
        path=f"/{path}",
        status_code=status_code,
        message=event_message(method, f"/{path}", status_code),
    )
    record_activity_event(get_activity_table(), event)


def _bundle_key(model_id: str, filename: str) -> str:
    return f"{model_id}/{filename}"


def _validate_bundle_name(bundle_name: str) -> str:
    normalized = bundle_name.strip()
    if not normalized:
        raise ValueError("Bundle name is required")
    if "/" in normalized:
        raise ValueError("Bundle name must not contain '/'")
    return normalized


def _public_model_url(key: str) -> str:
    return f"https://{MODELS_BUCKET}.s3.amazonaws.com/{key}"


def _s3_object_timestamp(value: Any) -> str:
    if not isinstance(value, datetime):
        raise ValueError("S3 object is missing a valid LastModified timestamp")
    return value.astimezone(timezone.utc).isoformat()


def _s3_object_summary(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = str(item.get("Key") or "")
    parts = key.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return {
        "bundle_name": parts[0],
        "name": parts[1],
        "key": key,
        "size_bytes": int(item.get("Size", 0)),
        "size_display": _format_bytes(item.get("Size", 0)),
        "last_modified_time": _s3_object_timestamp(item.get("LastModified")),
        "last_modified_display": _format_timestamp(_s3_object_timestamp(item.get("LastModified"))),
        "download_url": _public_model_url(key),
    }


def _bundle_file(bundle: Dict[str, Any], filename: str) -> Optional[Dict[str, Any]]:
    for item in bundle["files"]:
        if item["name"] == filename:
            return item
    return None


def _bundle_extra_files(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [item for item in bundle["files"] if item["name"] not in {MODEL_FILENAME, LABELS_FILENAME}]


def _bundle_row(bundle_name: str, files: List[Dict[str, Any]]) -> Dict[str, Any]:
    bundle_files = {"files": files}
    model_file = _bundle_file(bundle_files, MODEL_FILENAME)
    labels_file = _bundle_file(bundle_files, LABELS_FILENAME)
    latest_modified = max(file["last_modified_time"] for file in files)
    return {
        "bundle_name": bundle_name,
        "files": sorted(files, key=lambda item: item["name"]),
        "files_present": ", ".join(sorted(file["name"] for file in files)),
        "model_file": model_file,
        "labels_file": labels_file,
        "extra_files": _bundle_extra_files(bundle_files),
        "model_size_bytes": (model_file or {}).get("size_bytes", 0),
        "labels_size_bytes": (labels_file or {}).get("size_bytes", 0),
        "last_modified_time": latest_modified,
        "last_modified_display": _format_timestamp(latest_modified),
    }


def list_model_bundles() -> List[Dict[str, Any]]:
    s3_client = get_models_s3_client()
    continuation_token: Optional[str] = None
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    while True:
        params: Dict[str, Any] = {"Bucket": MODELS_BUCKET}
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        response = s3_client.list_objects_v2(**params)
        for item in response.get("Contents", []):
            summary = _s3_object_summary(item)
            if summary is None:
                continue
            grouped[summary["bundle_name"]].append(summary)
        if not response.get("IsTruncated"):
            break
        continuation_token = str(response.get("NextContinuationToken") or "")
        if not continuation_token:
            raise ValueError("Truncated S3 listing missing continuation token")
    return [_bundle_row(bundle_name, files) for bundle_name, files in grouped.items()]


def _model_bundle_csv_row(bundle: Dict[str, Any]) -> Dict[str, Any]:
    model_file = bundle.get("model_file") or {}
    labels_file = bundle.get("labels_file") or {}
    return {
        "bundle_name": bundle.get("bundle_name", ""),
        "files_present": bundle.get("files_present", ""),
        "model_url": model_file.get("download_url", ""),
        "labels_url": labels_file.get("download_url", ""),
        "model_size": model_file.get("size_display", ""),
        "labels_size": labels_file.get("size_display", ""),
        "last_modified": bundle.get("last_modified_display", ""),
    }


def upload_model_bundle(model_id: str, model_file: Any, labels_file: Any) -> None:
    bundle_name = _validate_bundle_name(model_id)
    if not model_file or not getattr(model_file, "filename", ""):
        raise ValueError("model.hef is required")
    if not labels_file or not getattr(labels_file, "filename", ""):
        raise ValueError("labels.txt is required")

    s3_client = get_models_s3_client()
    model_file.stream.seek(0)
    labels_file.stream.seek(0)
    model_key = _bundle_key(bundle_name, MODEL_FILENAME)
    labels_key = _bundle_key(bundle_name, LABELS_FILENAME)
    s3_client.upload_fileobj(
        model_file.stream,
        MODELS_BUCKET,
        model_key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    s3_client.upload_fileobj(
        labels_file.stream,
        MODELS_BUCKET,
        labels_key,
        ExtraArgs={"ContentType": "text/plain"},
    )


def delete_model_bundle(model_id: str) -> int:
    s3_client = get_models_s3_client()
    prefix = f"{_validate_bundle_name(model_id)}/"
    continuation_token: Optional[str] = None
    objects: List[Dict[str, str]] = []
    while True:
        params: Dict[str, Any] = {"Bucket": MODELS_BUCKET, "Prefix": prefix}
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        response = s3_client.list_objects_v2(**params)
        objects.extend({"Key": str(obj["Key"])} for obj in response.get("Contents", []))
        if not response.get("IsTruncated"):
            break
        continuation_token = str(response.get("NextContinuationToken") or "")
        if not continuation_token:
            raise ValueError("Truncated S3 delete listing missing continuation token")
    if not objects:
        return 0
    s3_client.delete_objects(Bucket=MODELS_BUCKET, Delete={"Objects": objects, "Quiet": True})
    return len(objects)


def _validate_s3_path(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("/") or ".." in normalized:
        raise ValueError("Invalid S3 path")
    return normalized


def _validate_s3_key(value: str) -> str:
    key = _validate_s3_path(value)
    if not key or key.endswith("/"):
        raise ValueError("S3 key is required")
    return key


def is_s3_image_key(key: str) -> bool:
    return any(key.lower().endswith(extension) for extension in S3_IMAGE_EXTENSIONS)


def _s3_file_row(item: Dict[str, Any]) -> Dict[str, Any]:
    modified = _s3_object_timestamp(item.get("LastModified"))
    key = str(item["Key"])
    return {
        "key": key,
        "name": key.rstrip("/").rsplit("/", 1)[-1],
        "is_image": is_s3_image_key(key),
        "size_bytes": int(item.get("Size", 0)),
        "size_display": _format_bytes(item.get("Size", 0)),
        "last_modified_time": modified,
        "last_modified_display": _format_timestamp(modified),
    }


def _s3_folder_row(prefix: str) -> Dict[str, str]:
    return {
        "prefix": prefix,
        "name": prefix.rstrip("/").rsplit("/", 1)[-1] + "/",
    }


def _s3_parent_prefix(prefix: str) -> str:
    parts = [part for part in prefix.strip("/").split("/") if part]
    return "/".join(parts[:-1]) + "/" if len(parts) > 1 else ""


def _s3_breadcrumbs(prefix: str) -> List[Dict[str, str]]:
    parts = [part for part in prefix.strip("/").split("/") if part]
    crumbs = [{"label": OUTPUT_BUCKET, "prefix": ""}]
    for index, part in enumerate(parts):
        crumbs.append({"label": part, "prefix": "/".join(parts[: index + 1]) + "/"})
    return crumbs


def list_output_s3(prefix: str, continuation_token: Optional[str], limit: int) -> Dict[str, Any]:
    params: Dict[str, Any] = {"Bucket": OUTPUT_BUCKET, "Prefix": prefix, "Delimiter": "/", "MaxKeys": limit}
    if continuation_token:
        params["ContinuationToken"] = continuation_token
    response = get_s3_client().list_objects_v2(**params)
    folders = [_s3_folder_row(item["Prefix"]) for item in response.get("CommonPrefixes", [])]
    files = [_s3_file_row(item) for item in response.get("Contents", []) if item["Key"] != prefix]
    return {"folders": folders, "files": files, "next_token": response.get("NextContinuationToken")}


def record_s3_activity(event_type: ActivityEventType, key: str, message: str) -> None:
    event = ActivityEvent(
        timestamp=utc_now(),
        source=ActivitySource.DASHBOARD,
        event_type=event_type,
        actor_type="dashboard",
        s3_bucket=OUTPUT_BUCKET,
        s3_key=key or None,
        message=message,
    )
    record_activity_event(get_activity_table(), event)


def _recent_s3_object_events(limit: int) -> List[ActivityEvent]:
    paginator = get_s3_client().get_paginator("list_objects_v2")
    objects: List[Dict[str, Any]] = []
    for page in paginator.paginate(Bucket=OUTPUT_BUCKET, Prefix="v1/", PaginationConfig={"PageSize": 500}):
        objects.extend(page.get("Contents", []))
    recent = sorted(objects, key=lambda item: item["LastModified"], reverse=True)[:limit]
    return [s3_object_event(OUTPUT_BUCKET, item) for item in recent]


def _recent_log_objects(limit: int) -> List[Dict[str, Any]]:
    objects = [event for event in _recent_s3_object_events(500) if event.s3_key and "/logs/" in event.s3_key]
    rows = [{"Key": event.s3_key, "LastModified": event.timestamp} for event in objects]
    return rows[:limit]


def _read_s3_text(key: str) -> str:
    response = get_s3_client().get_object(Bucket=OUTPUT_BUCKET, Key=key)
    return response["Body"].read().decode("utf-8")


def _recent_bugcam_events(limit: int) -> List[ActivityEvent]:
    events: List[ActivityEvent] = []
    for item in _recent_log_objects(5):
        key = str(item["Key"])
        events.extend(bugcam_log_events(OUTPUT_BUCKET, key, _read_s3_text(key), item["LastModified"]))
    return sorted(events, key=lambda event: event.timestamp, reverse=True)[:limit]


def _activity_row(event: Union[Dict[str, Any], ActivityEvent]) -> Dict[str, Any]:
    data = event.model_dump(mode="json", exclude_none=True) if isinstance(event, ActivityEvent) else dict(event)
    data["timestamp_display"] = _format_timestamp(data["timestamp"])
    return data


def _filter_activity_rows(rows: List[Dict[str, Any]], source: str, device_id: str, query: str) -> List[Dict[str, Any]]:
    query_lower = query.lower()
    return [
        row
        for row in rows
        if (not source or row.get("source") == source)
        and (not device_id or row.get("device_id") == device_id)
        and (not query or query_lower in f"{row.get('message', '')} {row.get('s3_key', '')} {row.get('path', '')}".lower())
    ]


def merged_activity_rows(source: str, device_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
    stored = list_activity_events(get_activity_table(), source, device_id, query, limit)
    live = [_activity_row(event) for event in _recent_s3_object_events(limit) + _recent_bugcam_events(limit)]
    rows = [_activity_row(item) for item in stored] + _filter_activity_rows(live, source, device_id, query)
    return sorted(rows, key=lambda row: row["timestamp"], reverse=True)[:limit]


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_timestamp(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return str(value or "")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_relative_age(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return ""
    now = datetime.now(timezone.utc)
    age = now - parsed.astimezone(timezone.utc)
    total_seconds = max(0, int(age.total_seconds()))
    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        minutes = total_seconds // 60
        unit = "min" if minutes == 1 else "mins"
        return f"{minutes} {unit} ago"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"
    days = total_seconds // 86400
    unit = "day" if days == 1 else "days"
    return f"{days} {unit} ago"


def _format_bytes(value: Any) -> str:
    if value in (None, ""):
        return ""
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    precision = 0 if unit_index == 0 else 1
    return f"{size:.{precision}f} {units[unit_index]}"


def _default_export_window() -> tuple[str, str]:
    return ("1970-01-01T00:00:00Z", datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))


def _build_export_url(table_name: str, *, enabled: bool = True) -> Optional[str]:
    if not enabled:
        return None
    params: Dict[str, Any] = {"table": table_name}
    for key in ("device_id", "track_id", "start_time", "end_time", "sort_by", "sort_desc"):
        value = request.args.get(key)
        if value not in (None, ""):
            params[key] = value
    return url_for("download_csv", **params)


def _stringify_csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _csv_response(filename: str, rows: List[Dict[str, Any]]) -> Response:
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key.startswith("_") or key.endswith("_url") or key.endswith("_preview"):
                continue
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames or ["message"])
    writer.writeheader()
    if rows:
        for row in rows:
            writer.writerow(
                {
                    key: _stringify_csv_value(value)
                    for key, value in row.items()
                    if key in fieldnames
                }
            )
    else:
        writer.writerow({"message": "No rows found"})
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _fetch_all_paginated(fetcher: Callable[..., Dict[str, Any]], **kwargs: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    while True:
        response = fetcher(limit=FETCH_ALL_PAGE_LIMIT, next_token=next_token, **kwargs)
        items.extend(response.get("items", []))
        next_token = response.get("next_token")
        if not next_token:
            return items


def _get_search_query() -> str:
    return request.args.get("search", "").strip()


def _row_matches_search(row: Dict[str, Any], search_query: str) -> bool:
    if not search_query:
        return True
    needle = search_query.lower()
    for key, value in row.items():
        if key.startswith("_") or key.endswith("_url") or key.endswith("_preview"):
            continue
        if needle in _stringify_csv_value(value).lower():
            return True
    return False


def _filter_rows_by_search(rows: List[Dict[str, Any]], search_query: str) -> List[Dict[str, Any]]:
    if not search_query:
        return rows
    return [row for row in rows if _row_matches_search(row, search_query)]


def _json_pretty(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _coerce_sort_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _json_pretty(value)
    return value


def _sort_local_rows(items: List[Dict[str, Any]], sort_by: str, sort_desc: bool) -> List[Dict[str, Any]]:
    if not items:
        return items

    def sort_key(item: Dict[str, Any]) -> Any:
        value = item.get(sort_by)
        if sort_by.endswith("time") or sort_by == "timestamp":
            parsed = _parse_timestamp(value)
            return parsed or datetime.min.replace(tzinfo=timezone.utc)
        return _coerce_sort_value(value)

    return sorted(items, key=sort_key, reverse=sort_desc)


def _get_limit(default: int = DEFAULT_PAGE_LIMIT) -> int:
    try:
        limit = int(request.args.get("limit", str(default)))
    except ValueError:
        return default
    return max(1, min(limit, MAX_PAGE_LIMIT))


def _get_page() -> int:
    try:
        return max(1, int(request.args.get("page", "1")))
    except ValueError:
        return 1


def _get_sort(sort_by_default: str, sort_desc_default: bool = True) -> tuple[str, bool]:
    sort_by = request.args.get("sort_by", sort_by_default)
    sort_desc_arg = request.args.get("sort_desc")
    if sort_desc_arg is None:
        return sort_by, sort_desc_default
    return sort_by, sort_desc_arg.lower() == "true"


def _build_query_url(endpoint: str, **updates: Any) -> str:
    params = request.args.to_dict(flat=True)
    for key, value in updates.items():
        if value in (None, "", False):
            params.pop(key, None)
        else:
            params[key] = str(value)
    return url_for(endpoint, **params)


def _token_pagination(next_token: Optional[str], endpoint: str, page: int, token_history: str) -> Dict[str, Any]:
    history_tokens = [token for token in token_history.split(",") if token]
    current_token = request.args.get("next_token")
    if current_token and page > len(history_tokens) + 1:
        history_tokens.append(current_token)

    if page <= 1:
        prev_url = None
    elif page == 2:
        prev_url = _build_query_url(endpoint, next_token=None, token_history=None, page=1)
    else:
        previous_token = history_tokens[page - 3] if len(history_tokens) >= page - 2 else None
        previous_history = ",".join(history_tokens[: page - 2])
        prev_url = _build_query_url(
            endpoint,
            next_token=previous_token,
            token_history=previous_history or None,
            page=page - 1,
        )

    next_history = ",".join(history_tokens)
    next_url = None
    if next_token:
        next_url = _build_query_url(
            endpoint,
            next_token=next_token,
            token_history=next_history or None,
            page=page + 1,
        )

    return {
        "page": page,
        "has_prev": prev_url is not None,
        "has_next": next_url is not None,
        "prev_url": prev_url,
        "next_url": next_url,
    }


def _local_pagination(items: List[Dict[str, Any]], endpoint: str, page: int, limit: int) -> Dict[str, Any]:
    start = (page - 1) * limit
    end = start + limit
    has_prev = page > 1
    has_next = end < len(items)
    return {
        "items": items[start:end],
        "pagination": {
            "page": page,
            "has_prev": has_prev,
            "has_next": has_next,
            "prev_url": _build_query_url(endpoint, page=page - 1) if has_prev else None,
            "next_url": _build_query_url(endpoint, page=page + 1) if has_next else None,
        },
        "count": len(items),
    }


def _build_sort_urls(columns: List[TableColumn], endpoint: str, current_sort_by: str, current_sort_desc: bool) -> Dict[str, str]:
    urls: Dict[str, str] = {}
    for column in columns:
        if not column.sortable:
            continue
        next_desc = "false" if current_sort_by == column.key and current_sort_desc else "true"
        urls[column.key] = _build_query_url(endpoint, sort_by=column.key, sort_desc=next_desc, next_token=None, token_history=None, page=1)
    return urls


def _normalize_track_row(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    normalized["timestamp"] = _format_timestamp(item.get("timestamp"))
    return normalized


def _normalize_classification_row(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    normalized["timestamp"] = _format_timestamp(item.get("timestamp"))
    return normalized


def _normalize_device_row(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    normalized["created"] = _format_timestamp(item.get("created"))
    parent_device_id = normalized.get("parent_device_id")
    has_parent = parent_device_id is not None and str(parent_device_id).strip() != ""
    normalized["device_type"] = "dot" if has_parent else "flick"
    return normalized


def _normalize_heartbeat_row(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    heartbeat_time = _parse_timestamp(item.get("timestamp"))
    normalized["_timestamp_raw"] = item.get("timestamp")
    normalized["timestamp"] = _format_timestamp(item.get("timestamp"))
    if heartbeat_time is None:
        normalized["status"] = "offline"
        normalized["age"] = ""
    else:
        age = datetime.now(timezone.utc) - heartbeat_time.astimezone(timezone.utc)
        normalized["status"] = "online" if age <= HEARTBEAT_ONLINE_THRESHOLD else "offline"
        normalized["age"] = _format_relative_age(item.get("timestamp"))
    normalized["cpu_temperature_celsius"] = (
        f"{float(item['cpu_temperature_celsius']):.1f}°C"
        if item.get("cpu_temperature_celsius") not in (None, "")
        else ""
    )
    normalized["storage_free_bytes"] = _format_bytes(item.get("storage_free_bytes"))
    normalized["storage_total_bytes"] = _format_bytes(item.get("storage_total_bytes"))
    return normalized


def _normalize_video_row(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    normalized["timestamp"] = _format_timestamp(item.get("timestamp"))
    normalized["video_link"] = item.get("video_key")
    return normalized


def _normalize_environment_row(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    normalized["timestamp"] = _format_timestamp(item.get("timestamp"))
    return normalized


def _normalize_deployment_row(item: Dict[str, Any], devices: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    normalized = dict(item)
    normalized["start_time"] = _format_timestamp(item.get("start_time"))
    normalized["end_time"] = _format_timestamp(item.get("end_time"))
    normalized["linked_devices"] = [device.get("device_id", "") for device in (devices or [])]
    normalized["image_preview"] = item.get("image_key")
    return normalized


def _model_form_defaults() -> Dict[str, Any]:
    return {
        "bundle_name": request.form.get("bundle_name", ""),
    }


def _visible_columns(
    base_columns: List[TableColumn],
    rows: List[Dict[str, Any]],
    *,
    include_extra_columns: bool = True,
) -> List[TableColumn]:
    if not include_extra_columns:
        return base_columns
    seen = {column.key for column in base_columns}
    extras: List[TableColumn] = []
    for row in rows:
        for key, value in row.items():
            if key in seen or key.startswith("_") or key.endswith("_url") or key.endswith("_preview"):
                continue
            kind = "json" if isinstance(value, (dict, list)) else "text"
            extras.append(TableColumn(key, key.replace("_", " ").title(), sortable=False, kind=kind))
            seen.add(key)
    return base_columns + extras


def _all_devices() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    while True:
        response = api.fetch_devices(limit=FETCH_ALL_PAGE_LIMIT, next_token=next_token, sort_by="device_id", sort_desc=False)
        items.extend(response.get("items", []))
        next_token = response.get("next_token")
        if not next_token:
            return items


def _device_ids() -> List[str]:
    return [item.get("device_id", "") for item in _all_devices() if item.get("device_id")]


def _all_deployments() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    while True:
        response = api.fetch_deployments(limit=FETCH_ALL_PAGE_LIMIT, next_token=next_token, sort_by="start_time", sort_desc=True)
        items.extend(response.get("items", []))
        next_token = response.get("next_token")
        if not next_token:
            return items


def _all_classifications_for_device(device_id: str, sort_by: str, sort_desc: bool) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    while True:
        response = api.fetch_classifications(
            device_id=device_id,
            limit=FETCH_ALL_PAGE_LIMIT,
            next_token=next_token,
            sort_by=sort_by,
            sort_desc=sort_desc,
        )
        items.extend(response.get("items", []))
        next_token = response.get("next_token")
        if not next_token:
            return items


def _count_devices() -> int:
    return len(_all_devices())


def _count_heartbeats() -> int:
    return len(api.fetch_heartbeats().get("items", []))


def _count_deployments() -> int:
    return len(_all_deployments())


def _count_model_bundles() -> int:
    return len(list_model_bundles())


def _table_context(
    *,
    title: str,
    description: str,
    endpoint: str,
    rows: List[Dict[str, Any]],
    columns: List[TableColumn],
    sort_by: str,
    sort_desc: bool,
    pagination: Dict[str, Any],
    filters: List[Dict[str, Any]],
    count: int,
    total_count: Optional[int] = None,
    info_message: Optional[str] = None,
    include_extra_columns: bool = True,
    export_url: Optional[str] = None,
    search_query: str = "",
) -> Dict[str, Any]:
    columns = _visible_columns(columns, rows, include_extra_columns=include_extra_columns)
    return {
        "title": title,
        "description": description,
        "endpoint": endpoint,
        "rows": rows,
        "columns": columns,
        "sort_by": sort_by,
        "sort_desc": sort_desc,
        "sort_urls": _build_sort_urls(columns, endpoint, sort_by, sort_desc),
        "pagination": pagination,
        "filters": filters,
        "count": count,
        "total_count": total_count if total_count is not None else count,
        "info_message": info_message,
        "export_url": export_url,
        "search_query": search_query,
    }


def _proxy_api_export(table_name: str) -> Response:
    start_time = request.args.get("start_time")
    end_time = request.args.get("end_time")
    if not start_time or not end_time:
        start_time, end_time = _default_export_window()
    params: Dict[str, Any] = {
        "table": table_name,
        "start_time": start_time,
        "end_time": end_time,
    }
    for key in ("device_id", "sort_by", "sort_desc"):
        value = request.args.get(key)
        if value not in (None, ""):
            params[key] = value
    response = requests.get(
        f"{API_BASE_URL}/export",
        params=params,
        headers=api._headers(),
        timeout=60,
    )
    response.raise_for_status()
    flask_response = make_response(response.content)
    flask_response.headers["Content-Type"] = response.headers.get("Content-Type", "text/csv")
    flask_response.headers["Content-Disposition"] = response.headers.get(
        "Content-Disposition",
        f'attachment; filename="{table_name}_export.csv"',
    )
    return flask_response


def _local_csv_rows(table_name: str) -> List[Dict[str, Any]]:
    device_id = request.args.get("device_id") or None
    track_id = request.args.get("track_id") or None
    sort_by = request.args.get("sort_by") or "timestamp"
    sort_desc = request.args.get("sort_desc", "true").lower() == "true"

    if table_name == "tracks":
        rows = _fetch_all_paginated(api.fetch_tracks, device_id=device_id, sort_by=sort_by, sort_desc=sort_desc)
        return [_normalize_track_row(item) for item in rows]
    if table_name == "classifications":
        if track_id:
            resolved_device_id = device_id
            if not resolved_device_id:
                track = api.get_track(track_id)
                resolved_device_id = str(track.get("device_id") or "")
            if not resolved_device_id:
                return []
            rows = _all_classifications_for_device(resolved_device_id, sort_by, sort_desc)
            return [_normalize_classification_row(item) for item in rows if item.get("track_id") == track_id]
        if not device_id:
            return []
        rows = _fetch_all_paginated(
            api.fetch_classifications,
            device_id=device_id,
            sort_by=sort_by,
            sort_desc=sort_desc,
        )
        return [_normalize_classification_row(item) for item in rows]
    if table_name == "devices":
        rows = _fetch_all_paginated(api.fetch_devices, device_id=device_id, sort_by=sort_by, sort_desc=sort_desc)
        return [_normalize_device_row(item) for item in rows]
    if table_name == "heartbeats":
        return [_normalize_heartbeat_row(item) for item in api.fetch_heartbeats().get("items", [])]
    if table_name == "models":
        model_sort_by = sort_by if sort_by != "timestamp" else "last_modified_time"
        rows = _sort_local_rows(list_model_bundles(), model_sort_by, sort_desc)
        return [_model_bundle_csv_row(item) for item in rows]
    if table_name == "videos":
        if not device_id:
            return []
        rows = _fetch_all_paginated(api.fetch_videos, device_id=device_id, sort_by=sort_by, sort_desc=sort_desc)
        return [_normalize_video_row(item) for item in rows]
    if table_name == "deployments":
        rows: List[Dict[str, Any]] = []
        for item in _fetch_all_paginated(api.fetch_deployments, sort_by=sort_by, sort_desc=sort_desc):
            details = api.get_deployment(item["deployment_id"])
            rows.append(_normalize_deployment_row(details.get("deployment", item), details.get("devices", [])))
        return rows
    if table_name == "environment":
        rows = _fetch_all_paginated(api.fetch_environment, device_id=device_id, sort_by=sort_by, sort_desc=sort_desc)
        return [_normalize_environment_row(item) for item in rows]
    raise ValueError(f"Unsupported table for CSV export: {table_name}")


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if not _dashboard_auth_enabled():
        return redirect(url_for("index"))
    if _dashboard_is_authenticated():
        return redirect(request.args.get("next") or url_for("index"))
    error: Optional[str] = None
    next_url = request.args.get("next") or request.form.get("next") or url_for("index")
    if request.method == "POST":
        submitted_password = request.form.get("password", "")
        if hmac.compare_digest(submitted_password, DASHBOARD_PASSWORD):
            session.permanent = True
            session["dashboard_auth"] = _dashboard_auth_token()
            return redirect(next_url)
        error = "Wrong password"
    return render_template("login.html", error=error, next_url=next_url, show_nav=False)


@app.route("/health")
def health_check() -> tuple[Response, int]:
    return (
        jsonify(
            {
                "status": "healthy",
                "message": "Dashboard is healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": {
                    "API_BASE_URL": API_BASE_URL,
                    "SENSING_GARDEN_API_KEY": "Present" if API_KEY else "Not set",
                },
            }
        ),
        200,
    )


@app.route("/download_csv")
def download_csv() -> Response:
    table_name = request.args.get("table")
    if not table_name:
        return make_response("table parameter is required", 400)
    try:
        if table_name in EXPORTABLE_API_TABLES and not (table_name == "classifications" and request.args.get("track_id")):
            return _proxy_api_export(table_name)
        rows = _local_csv_rows(table_name)
        return _csv_response(f"{table_name}_export.csv", rows)
    except Exception as exc:
        return make_response(str(exc), 500)


@app.route("/")
def index() -> str:
    try:
        counts = [
            {"name": "Tracks", "count": api.count_tracks(), "endpoint": "view_tracks"},
            {"name": "Classifications", "count": api.count_classifications(), "endpoint": "view_classifications"},
            {"name": "Devices", "count": _count_devices(), "endpoint": "view_devices"},
            {"name": "Heartbeats", "count": _count_heartbeats(), "endpoint": "view_heartbeats"},
            {"name": "Models", "count": _count_model_bundles(), "endpoint": "view_models"},
            {"name": "Videos", "count": api.count_videos(), "endpoint": "view_videos"},
            {"name": "Deployments", "count": _count_deployments(), "endpoint": "view_deployments"},
            {"name": "Environmental Readings", "count": api.count_environment(), "endpoint": "view_environment"},
        ]
        return render_template("index.html", counts=counts)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/tracks")
def view_tracks() -> str:
    device_id = request.args.get("device_id") or None
    search_query = _get_search_query()
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("timestamp", True)
    token_history = request.args.get("token_history", "")
    try:
        if search_query:
            rows = [
                _normalize_track_row(item)
                for item in _fetch_all_paginated(
                    api.fetch_tracks,
                    device_id=device_id,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                )
            ]
            rows = _filter_rows_by_search(rows, search_query)
            paged = _local_pagination(rows, "view_tracks", page, limit)
            context = _table_context(
                title="Tracks",
                description="Inspectable track records from the API.",
                endpoint="view_tracks",
                rows=paged["items"],
                columns=TRACK_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination=paged["pagination"],
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=len(paged["items"]),
                total_count=paged["count"],
                include_extra_columns=False,
                export_url=_build_export_url("tracks"),
                search_query=search_query,
            )
        else:
            response = api.fetch_tracks(
                device_id=device_id,
                limit=limit,
                next_token=request.args.get("next_token"),
                sort_by=sort_by,
                sort_desc=sort_desc,
            )
            rows = [_normalize_track_row(item) for item in response.get("items", [])]
            context = _table_context(
                title="Tracks",
                description="Inspectable track records from the API.",
                endpoint="view_tracks",
                rows=rows,
                columns=TRACK_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination=_token_pagination(response.get("next_token"), "view_tracks", page, token_history),
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=response.get("count", len(rows)),
                total_count=api.count_tracks(device_id=device_id),
                include_extra_columns=False,
                export_url=_build_export_url("tracks"),
                search_query=search_query,
            )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/tracks/<track_id>")
def view_track_detail(track_id: str) -> str:
    try:
        track = _normalize_track_row(api.get_track(track_id))
        if not track:
            return render_template("error.html", error=f"Track {track_id} not found")
        classification_url = url_for("view_classifications", track_id=track_id, device_id=track.get("device_id"))
        return render_template(
            "track_detail.html",
            track=track,
            track_json=_json_pretty(track),
            classification_url=classification_url,
        )
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/classifications")
def view_classifications() -> str:
    device_id = request.args.get("device_id") or None
    track_id = request.args.get("track_id") or None
    search_query = _get_search_query()
    limit = _get_limit()
    sort_by, sort_desc = _get_sort("timestamp", True)
    try:
        if track_id:
            if not device_id:
                track = api.get_track(track_id)
                device_id = str(track.get("device_id") or "")
            if not device_id:
                raise ValueError(f"Track {track_id} was not found")
            rows = [_normalize_classification_row(item) for item in _all_classifications_for_device(device_id, sort_by, sort_desc)]
            rows = [row for row in rows if row.get("track_id") == track_id]
            rows = _filter_rows_by_search(rows, search_query)
            paged = _local_pagination(rows, "view_classifications", _get_page(), limit)
            context = _table_context(
                title="Classifications",
                description="All classification rows, with device and track filtering.",
                endpoint="view_classifications",
                rows=paged["items"],
                columns=CLASSIFICATION_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination=paged["pagination"],
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                    {"name": "track_id", "label": "Track ID", "value": track_id, "type": "text"},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=len(paged["items"]),
                total_count=paged["count"],
                export_url=_build_export_url("classifications"),
                search_query=search_query,
            )
        elif not device_id:
            context = _table_context(
                title="Classifications",
                description="All classification rows, with device and track filtering.",
                endpoint="view_classifications",
                rows=[],
                columns=CLASSIFICATION_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination={},
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": "", "options": _device_ids()},
                    {"name": "track_id", "label": "Track ID", "value": "", "type": "text"},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=0,
                total_count=0,
                info_message="Select a device to view classifications.",
                export_url=None,
                search_query=search_query,
            )
        else:
            page = _get_page()
            token_history = request.args.get("token_history", "")
            if search_query:
                rows = [
                    _normalize_classification_row(item)
                    for item in _fetch_all_paginated(
                        api.fetch_classifications,
                        device_id=device_id,
                        sort_by=sort_by,
                        sort_desc=sort_desc,
                    )
                ]
                rows = _filter_rows_by_search(rows, search_query)
                paged = _local_pagination(rows, "view_classifications", page, limit)
                context = _table_context(
                    title="Classifications",
                    description="All classification rows, with device and track filtering.",
                    endpoint="view_classifications",
                    rows=paged["items"],
                    columns=CLASSIFICATION_COLUMNS,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                    pagination=paged["pagination"],
                    filters=[
                        {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                        {"name": "track_id", "label": "Track ID", "value": "", "type": "text"},
                        {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                    ],
                    count=len(paged["items"]),
                    total_count=paged["count"],
                    export_url=_build_export_url("classifications"),
                    search_query=search_query,
                )
            else:
                response = api.fetch_classifications(
                    device_id=device_id,
                    limit=limit,
                    next_token=request.args.get("next_token"),
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                )
                rows = [_normalize_classification_row(item) for item in response.get("items", [])]
                context = _table_context(
                    title="Classifications",
                    description="All classification rows, with device and track filtering.",
                    endpoint="view_classifications",
                    rows=rows,
                    columns=CLASSIFICATION_COLUMNS,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                    pagination=_token_pagination(response.get("next_token"), "view_classifications", page, token_history),
                    filters=[
                        {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                        {"name": "track_id", "label": "Track ID", "value": "", "type": "text"},
                        {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                    ],
                    count=response.get("count", len(rows)),
                    total_count=api.count_classifications(device_id=device_id),
                    export_url=_build_export_url("classifications"),
                    search_query=search_query,
                )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/devices")
def view_devices() -> str:
    device_id = request.args.get("device_id") or None
    search_query = _get_search_query()
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("device_id", False)
    token_history = request.args.get("token_history", "")
    try:
        if search_query:
            rows = [
                _normalize_device_row(item)
                for item in _fetch_all_paginated(
                    api.fetch_devices,
                    device_id=device_id,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                )
            ]
            rows = _filter_rows_by_search(rows, search_query)
            paged = _local_pagination(rows, "view_devices", page, limit)
            context = _table_context(
                title="Devices",
                description="Registered devices. Flicks have no parent; dots do.",
                endpoint="view_devices",
                rows=paged["items"],
                columns=DEVICE_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination=paged["pagination"],
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=len(paged["items"]),
                total_count=paged["count"],
                export_url=_build_export_url("devices"),
                search_query=search_query,
            )
        else:
            response = api.fetch_devices(
                device_id=device_id,
                limit=limit,
                next_token=request.args.get("next_token"),
                sort_by=sort_by,
                sort_desc=sort_desc,
            )
            rows = [_normalize_device_row(item) for item in response.get("items", [])]
            context = _table_context(
                title="Devices",
                description="Registered devices. Flicks have no parent; dots do.",
                endpoint="view_devices",
                rows=rows,
                columns=DEVICE_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination=_token_pagination(response.get("next_token"), "view_devices", page, token_history),
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=response.get("count", len(rows)),
                total_count=_count_devices(),
                export_url=_build_export_url("devices"),
                search_query=search_query,
            )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/heartbeats")
def view_heartbeats() -> str:
    search_query = _get_search_query()
    sort_by, sort_desc = _get_sort("timestamp", True)
    device_id_filter = request.args.get("device_id", "")
    try:
        if device_id_filter:
            response = api.fetch_heartbeats(device_id=device_id_filter)
            description = f"All heartbeats for {device_id_filter}."
        else:
            response = api.fetch_heartbeats()
            description = "Latest heartbeat per device."
        items = [_normalize_heartbeat_row(item) for item in response.get("items", [])]
        for item in items:
            item["_device_id_raw"] = str(item.get("device_id") or "")
        items = _filter_rows_by_search(items, search_query)
        paged = _local_pagination(items, "view_heartbeats", _get_page(), _get_limit())
        context = _table_context(
            title="Heartbeats",
            description=description,
            endpoint="view_heartbeats",
            rows=paged["items"],
            columns=HEARTBEAT_COLUMNS,
            sort_by=sort_by,
            sort_desc=sort_desc,
            pagination=paged["pagination"],
            filters=[
                {"name": "device_id", "label": "Device ID", "value": device_id_filter, "options": _device_ids()},
            ],
            count=len(paged["items"]),
            total_count=paged["count"],
            export_url=_build_export_url("heartbeats"),
            search_query=search_query,
        )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/models")
def view_models() -> str:
    search_query = _get_search_query()
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("last_modified_time", True)
    sort_columns = _visible_columns(MODEL_COLUMNS, [], include_extra_columns=False)
    try:
        rows = _sort_local_rows(list_model_bundles(), sort_by, sort_desc)
        rows = _filter_rows_by_search(rows, search_query)
        paged = _local_pagination(rows, "view_models", page, limit)
        return render_template(
            "models.html",
            title="Models",
            description=f"S3-backed model bundles from {MODELS_BUCKET}.",
            bundles=paged["items"],
            sort_by=sort_by,
            sort_desc=sort_desc,
            sort_urls=_build_sort_urls(sort_columns, "view_models", sort_by, sort_desc),
            pagination=paged["pagination"],
            total_count=paged["count"],
            count=len(paged["items"]),
            web_read_only=WEB_READ_ONLY,
            export_url=_build_export_url("models"),
            search_query=search_query,
        )
    except Exception as exc:
        return render_template(
            "models.html",
            bundles=[],
            error=str(exc),
            sort_urls={},
            pagination={},
            total_count=0,
            count=0,
            web_read_only=WEB_READ_ONLY,
            export_url=_build_export_url("models"),
            search_query=search_query,
        )


@app.route("/videos")
def view_videos() -> str:
    device_id = request.args.get("device_id") or None
    search_query = _get_search_query()
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("timestamp", True)
    token_history = request.args.get("token_history", "")
    try:
        if not device_id:
            context = _table_context(
                title="Videos",
                description="Video records with presigned links when available.",
                endpoint="view_videos",
                rows=[],
                columns=VIDEO_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination={},
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": "", "options": _device_ids()},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=0,
                total_count=0,
                info_message="Select a device to view videos.",
                export_url=None,
                search_query=search_query,
            )
        else:
            if search_query:
                rows = [
                    _normalize_video_row(item)
                    for item in _fetch_all_paginated(
                        api.fetch_videos,
                        device_id=device_id,
                        sort_by=sort_by,
                        sort_desc=sort_desc,
                    )
                ]
                rows = _filter_rows_by_search(rows, search_query)
                paged = _local_pagination(rows, "view_videos", page, limit)
                context = _table_context(
                    title="Videos",
                    description="Video records with presigned links when available.",
                    endpoint="view_videos",
                    rows=paged["items"],
                    columns=VIDEO_COLUMNS,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                    pagination=paged["pagination"],
                    filters=[
                        {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                        {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                    ],
                    count=len(paged["items"]),
                    total_count=paged["count"],
                    export_url=_build_export_url("videos"),
                    search_query=search_query,
                )
            else:
                response = api.fetch_videos(
                    device_id=device_id,
                    limit=limit,
                    next_token=request.args.get("next_token"),
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                )
                rows = [_normalize_video_row(item) for item in response.get("items", [])]
                context = _table_context(
                    title="Videos",
                    description="Video records with presigned links when available.",
                    endpoint="view_videos",
                    rows=rows,
                    columns=VIDEO_COLUMNS,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                    pagination=_token_pagination(response.get("next_token"), "view_videos", page, token_history),
                    filters=[
                        {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                        {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                    ],
                    count=response.get("count", len(rows)),
                    total_count=api.count_videos(device_id=device_id),
                    export_url=_build_export_url("videos"),
                    search_query=search_query,
                )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/deployments")
def view_deployments() -> str:
    search_query = _get_search_query()
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("start_time", True)
    token_history = request.args.get("token_history", "")
    try:
        response = api.fetch_deployments(
            limit=limit,
            next_token=request.args.get("next_token"),
            sort_by=sort_by,
            sort_desc=sort_desc,
        )
        rows: List[Dict[str, Any]] = []
        for item in response.get("items", []):
            details = api.get_deployment(item["deployment_id"])
            rows.append(_normalize_deployment_row(details.get("deployment", item), details.get("devices", [])))
        if search_query:
            all_rows = rows
            next_token = response.get("next_token")
            while next_token:
                extra_response = api.fetch_deployments(
                    limit=FETCH_ALL_PAGE_LIMIT,
                    next_token=next_token,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                )
                for item in extra_response.get("items", []):
                    details = api.get_deployment(item["deployment_id"])
                    all_rows.append(_normalize_deployment_row(details.get("deployment", item), details.get("devices", [])))
                next_token = extra_response.get("next_token")
            rows = _filter_rows_by_search(all_rows, search_query)
            paged = _local_pagination(rows, "view_deployments", page, limit)
            pagination = paged["pagination"]
            visible_rows = paged["items"]
            total_count = paged["count"]
            page_count = len(visible_rows)
        else:
            pagination = _token_pagination(response.get("next_token"), "view_deployments", page, token_history)
            visible_rows = rows
            total_count = _count_deployments()
            page_count = len(rows)
        context = _table_context(
            title="Deployments",
            description="Deployment records plus linked device assignments.",
            endpoint="view_deployments",
            rows=visible_rows,
            columns=DEPLOYMENT_COLUMNS,
            sort_by=sort_by,
            sort_desc=sort_desc,
            pagination=pagination,
            filters=[{"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]}],
            count=page_count,
            total_count=total_count,
            export_url=_build_export_url("deployments"),
            search_query=search_query,
        )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/environment")
def view_environment() -> str:
    device_id = request.args.get("device_id") or None
    search_query = _get_search_query()
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("timestamp", True)
    token_history = request.args.get("token_history", "")
    try:
        if search_query:
            rows = [
                _normalize_environment_row(item)
                for item in _fetch_all_paginated(
                    api.fetch_environment,
                    device_id=device_id,
                    sort_by=sort_by,
                    sort_desc=sort_desc,
                )
            ]
            rows = _filter_rows_by_search(rows, search_query)
            paged = _local_pagination(rows, "view_environment", page, limit)
            context = _table_context(
                title="Environmental Readings",
                description="Environmental readings returned by the backend API.",
                endpoint="view_environment",
                rows=paged["items"],
                columns=ENVIRONMENT_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination=paged["pagination"],
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=len(paged["items"]),
                total_count=paged["count"],
                export_url=_build_export_url("environment"),
                search_query=search_query,
            )
        else:
            response = api.fetch_environment(
                device_id=device_id,
                limit=limit,
                next_token=request.args.get("next_token"),
                sort_by=sort_by,
                sort_desc=sort_desc,
            )
            rows = [_normalize_environment_row(item) for item in response.get("items", [])]
            context = _table_context(
                title="Environmental Readings",
                description="Environmental readings returned by the backend API.",
                endpoint="view_environment",
                rows=rows,
                columns=ENVIRONMENT_COLUMNS,
                sort_by=sort_by,
                sort_desc=sort_desc,
                pagination=_token_pagination(response.get("next_token"), "view_environment", page, token_history),
                filters=[
                    {"name": "device_id", "label": "Device ID", "value": device_id or "", "options": _device_ids()},
                    {"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]},
                ],
                count=response.get("count", len(rows)),
                total_count=api.count_environment(device_id=device_id),
                export_url=_build_export_url("environment"),
                search_query=search_query,
            )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/image_proxy")
def image_proxy() -> Any:
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    parsed = urlparse(url)
    if parsed.scheme != "https" or "amazonaws.com" not in parsed.netloc:
        return jsonify({"error": "URL not allowed"}), 400
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch image"}), response.status_code
        proxy_response = make_response(response.content)
        proxy_response.headers["Content-Type"] = response.headers.get("Content-Type", "image/jpeg")
        proxy_response.headers["Access-Control-Allow-Origin"] = "*"
        return proxy_response
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/add_model", methods=["GET"])
def add_model() -> Any:
    if WEB_READ_ONLY:
        return render_template("error.html", error="Model management is disabled in read-only mode"), 403
    return render_template("add_model.html", form_values=_model_form_defaults())


@app.route("/add_model", methods=["POST"])
def add_model_submit() -> Any:
    if WEB_READ_ONLY:
        return render_template("error.html", error="Model management is disabled in read-only mode"), 403
    try:
        upload_model_bundle(
            request.form.get("bundle_name", ""),
            request.files.get("model_file"),
            request.files.get("labels_file"),
        )
        return redirect(url_for("view_models"))
    except Exception as exc:
        return (
            render_template(
                "add_model.html",
                error=str(exc),
                form_values=_model_form_defaults(),
            ),
            400,
        )


@app.route("/models/<model_id>/delete", methods=["POST"])
def delete_model(model_id: str) -> Any:
    if WEB_READ_ONLY:
        return render_template("error.html", error="Model deletion is disabled in read-only mode"), 403
    try:
        delete_model_bundle(model_id)
        return redirect(url_for("view_models"))
    except Exception as exc:
        return render_template("error.html", error=str(exc)), 500


@app.route("/s3")
def view_s3_browser() -> str:
    try:
        prefix = _validate_s3_path(request.args.get("prefix", ""))
        limit = _get_limit()
        listing = list_output_s3(prefix, request.args.get("continuation_token"), limit)
        record_s3_activity(ActivityEventType.S3_LIST, prefix, f"Listed s3://{OUTPUT_BUCKET}/{prefix}")
        return render_template(
            "s3_browser.html",
            bucket=OUTPUT_BUCKET,
            prefix=prefix,
            parent_prefix=_s3_parent_prefix(prefix),
            breadcrumbs=_s3_breadcrumbs(prefix),
            folders=listing["folders"],
            files=listing["files"],
            next_token=listing["next_token"],
            limit=limit,
        )
    except Exception as exc:
        return render_template("error.html", error=str(exc)), 500


@app.route("/api/s3/list")
def api_s3_list() -> Response:
    try:
        prefix = _validate_s3_path(request.args.get("prefix", ""))
        limit = _get_limit()
        listing = list_output_s3(prefix, request.args.get("continuation_token"), limit)
        record_s3_activity(ActivityEventType.S3_LIST, prefix, f"Listed s3://{OUTPUT_BUCKET}/{prefix}")
        return jsonify(listing)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/s3/open")
def api_s3_open() -> Response:
    try:
        key = _validate_s3_key(request.args.get("key", ""))
        url = get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": OUTPUT_BUCKET, "Key": key},
            ExpiresIn=3600,
        )
        record_s3_activity(ActivityEventType.S3_OPEN, key, f"Opened s3://{OUTPUT_BUCKET}/{key}")
        return jsonify({"url": url})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/admin/logs")
def admin_logs() -> str:
    return render_template(
        "activity_logs.html",
        sources=[source.value for source in ActivitySource],
        source=request.args.get("source", ""),
        device_id=request.args.get("device_id", ""),
        query=request.args.get("q", ""),
        limit=_get_limit(100),
    )


@app.route("/api/admin/activity")
def api_admin_activity() -> Response:
    rows = merged_activity_rows(
        request.args.get("source", ""),
        request.args.get("device_id", ""),
        request.args.get("q", ""),
        _get_limit(100),
    )
    return jsonify({"items": rows, "count": len(rows)})


@app.route("/admin")
def admin() -> str:
    return render_template("admin.html", device_ids=_device_ids())


@app.route("/api/admin/device-summary")
def admin_device_summary() -> Response:
    device_ids = _device_ids()
    devices: Dict[str, Dict[str, Any]] = {}
    for device_id in device_ids:
        try:
            total = api.count_videos(device_id)
            oldest_timestamp = None
            newest_timestamp = None
            oldest = api.fetch_videos(device_id=device_id, limit=1, sort_by="timestamp", sort_desc=False)
            newest = api.fetch_videos(device_id=device_id, limit=1, sort_by="timestamp", sort_desc=True)
            if oldest.get("items"):
                oldest_timestamp = oldest["items"][0].get("timestamp")
            if newest.get("items"):
                newest_timestamp = newest["items"][0].get("timestamp")
            devices[device_id] = {
                "total_videos": total,
                "oldest_timestamp": oldest_timestamp,
                "newest_timestamp": newest_timestamp,
            }
        except Exception as exc:
            devices[device_id] = {"error": str(exc)}
    return jsonify({"devices": devices})


@app.route("/api/admin/video-counts")
def admin_video_counts() -> Response:
    requested_device_id = request.args.get("device_id")
    device_ids = [requested_device_id] if requested_device_id else _device_ids()
    counts_by_device: Dict[str, Dict[str, int]] = {}
    for device_id in device_ids:
        counts: Dict[str, int] = defaultdict(int)
        next_token: Optional[str] = None
        while True:
            response = api.fetch_videos(
                device_id=device_id,
                limit=FETCH_ALL_PAGE_LIMIT,
                next_token=next_token,
                sort_by="timestamp",
                sort_desc=True,
            )
            for item in response.get("items", []):
                timestamp = str(item.get("timestamp", ""))
                counts[timestamp[:10]] += 1
            next_token = response.get("next_token")
            if not next_token:
                break
        counts_by_device[device_id] = dict(sorted(counts.items()))
    return jsonify(counts_by_device)


@app.route("/api/admin/s3-orphans")
def admin_s3_orphans() -> Any:
    try:
        s3 = get_s3_client()
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("sensing-garden-videos")
        s3_files: List[Dict[str, Any]] = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=VIDEOS_BUCKET, Prefix="videos/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".mp4"):
                    s3_files.append(
                        {
                            "key": key,
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                        }
                    )

        db_keys: set[str] = set()
        scan_kwargs: Dict[str, Any] = {"ProjectionExpression": "video_key"}
        while True:
            response = table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                if "video_key" in item:
                    db_keys.add(item["video_key"])
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        orphans = [item for item in s3_files if item["key"] not in db_keys]
        record_s3_activity(ActivityEventType.S3_LIST, "videos/", "Checked video S3 orphans")
        return jsonify(
            {
                "total_s3_files": len(s3_files),
                "orphan_count": len(orphans),
                "orphans": orphans[:500],
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/admin/s3-presign")
def admin_s3_presign() -> Any:
    key = request.args.get("key")
    if not key:
        return jsonify({"error": "key parameter required"}), 400
    if not key.startswith("videos/") or not key.endswith(".mp4"):
        return jsonify({"error": "Invalid key"}), 400
    try:
        url = get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": VIDEOS_BUCKET, "Key": key},
            ExpiresIn=3600,
        )
        record_s3_activity(ActivityEventType.S3_OPEN, key, f"Opened s3://{VIDEOS_BUCKET}/{key}")
        return jsonify({"url": url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/admin/orphaned-devices")
def api_admin_orphaned_devices() -> Any:
    try:
        result = api._request("GET", "admin/orphaned-devices")
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
