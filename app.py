import csv
import hashlib
import io
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import boto3
import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, make_response, redirect, render_template, request, url_for


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "sensing-garden-dashboard-dev")

API_BASE_URL = os.getenv("API_BASE_URL", "https://nxdp0npcb2.execute-api.us-east-1.amazonaws.com")
API_KEY = os.getenv("SENSING_GARDEN_API_KEY", "")
MODELS_BUCKET = os.getenv("MODELS_BUCKET", "scl-sensing-garden-models")
VIDEOS_BUCKET = os.getenv("VIDEOS_BUCKET", "scl-sensing-garden-videos")
IMAGES_BUCKET = os.getenv("IMAGES_BUCKET", "scl-sensing-garden-images")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "scl-sensing-garden")
MODEL_FILENAME = "model.hef"
LABELS_FILENAME = "labels.txt"
HEARTBEAT_ONLINE_THRESHOLD = timedelta(hours=2)
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200
FETCH_ALL_PAGE_LIMIT = 500
WEB_READ_ONLY = os.getenv("WEB_READ_ONLY", "true").lower() in {"1", "true", "yes", "on"}
EXPORTABLE_API_TABLES = {"classifications", "devices", "models", "videos", "environment"}


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
        response = requests.request(
            method,
            f"{self.base_url}/{endpoint.lstrip('/')}",
            params=params,
            json=body,
            headers={**self._headers(), "Content-Type": "application/json"},
            timeout=30,
        )
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

    def fetch_heartbeats(self) -> Dict[str, Any]:
        return self._request("GET", "heartbeats")

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
    TableColumn("id", "Model ID"),
    TableColumn("timestamp", "Timestamp"),
    TableColumn("name", "Name"),
    TableColumn("description", "Description"),
    TableColumn("version", "Version"),
    TableColumn("metadata", "Metadata", sortable=False, kind="json"),
]


@app.context_processor
def inject_web_mode() -> Dict[str, Any]:
    return {"web_read_only": WEB_READ_ONLY}


def get_models_s3_client() -> Any:
    client_kwargs: Dict[str, str] = {}
    if os.getenv("AWS_ACCESS_KEY_ID"):
        client_kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID", "")
    if os.getenv("AWS_SECRET_ACCESS_KEY"):
        client_kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if os.getenv("AWS_SESSION_TOKEN"):
        client_kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN", "")
    if os.getenv("AWS_REGION"):
        client_kwargs["region_name"] = os.getenv("AWS_REGION", "")
    return boto3.client("s3", **client_kwargs)


def _bundle_key(model_id: str, filename: str) -> str:
    return f"{model_id}/{filename}"


def _compute_stream_sha256(file_storage: Any) -> str:
    hasher = hashlib.sha256()
    file_storage.stream.seek(0)
    while True:
        chunk = file_storage.stream.read(1024 * 1024)
        if not chunk:
            break
        hasher.update(chunk)
    file_storage.stream.seek(0)
    return hasher.hexdigest()


def _normalize_s3_head(head: Dict[str, Any]) -> Dict[str, str]:
    normalized = {"etag": str(head.get("ETag", "")).strip('"')}
    version_id = head.get("VersionId")
    if version_id:
        normalized["version_id"] = str(version_id)
    return normalized


def upload_model_bundle(model_id: str, model_file: Any, labels_file: Any) -> Dict[str, Any]:
    if not model_file or not getattr(model_file, "filename", ""):
        raise ValueError("model.hef is required")
    if not labels_file or not getattr(labels_file, "filename", ""):
        raise ValueError("labels.txt is required")

    s3_client = get_models_s3_client()
    uploaded_at = datetime.now(timezone.utc).isoformat()
    model_sha256 = _compute_stream_sha256(model_file)
    labels_sha256 = _compute_stream_sha256(labels_file)
    model_file.stream.seek(0)
    labels_file.stream.seek(0)
    model_key = _bundle_key(model_id, MODEL_FILENAME)
    labels_key = _bundle_key(model_id, LABELS_FILENAME)
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
    model_head = _normalize_s3_head(s3_client.head_object(Bucket=MODELS_BUCKET, Key=model_key))
    labels_head = _normalize_s3_head(s3_client.head_object(Bucket=MODELS_BUCKET, Key=labels_key))
    provenance = {
        "bundle_uploaded_at": uploaded_at,
        "model_id": model_id,
        "bundle_key_model": model_key,
        "bundle_key_labels": labels_key,
        "model_sha256": model_sha256,
        "labels_sha256": labels_sha256,
        "model_etag": model_head["etag"],
        "labels_etag": labels_head["etag"],
    }
    if "version_id" in model_head:
        provenance["model_version_id"] = model_head["version_id"]
    if "version_id" in labels_head:
        provenance["labels_version_id"] = labels_head["version_id"]
    return provenance


def delete_model_bundle(model_id: str) -> int:
    s3_client = get_models_s3_client()
    prefix = f"{model_id}/"
    response = s3_client.list_objects_v2(Bucket=MODELS_BUCKET, Prefix=prefix)
    objects = [{"Key": obj["Key"]} for obj in response.get("Contents", [])]
    if not objects:
        return 0
    s3_client.delete_objects(Bucket=MODELS_BUCKET, Delete={"Objects": objects, "Quiet": True})
    return len(objects)


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


def _truncate_identifier(value: Any, prefix: int = 8) -> str:
    text = str(value or "")
    if len(text) <= prefix:
        return text
    return f"{text[:prefix]}..."


def _device_display_names() -> Dict[str, str]:
    names: Dict[str, str] = {}
    for item in _all_devices():
        device_id = str(item.get("device_id") or "")
        if not device_id:
            continue
        for key in ("device_name", "name", "label", "display_name"):
            candidate = item.get(key)
            if candidate not in (None, ""):
                names[device_id] = str(candidate)
                break
    return names


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


def _normalize_model_row(item: Dict[str, Any]) -> Dict[str, Any]:
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


def _model_bundle_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        bundle = metadata.get("bundle")
        if isinstance(bundle, dict):
            return bundle
    return {}


def _short_hash(value: str) -> str:
    return value[:12] if value else ""


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
        device_names = _device_display_names()
        rows = [_normalize_heartbeat_row(item) for item in api.fetch_heartbeats().get("items", [])]
        for item in rows:
            raw_device_id = str(item.get("device_id") or "")
            item["device_id"] = device_names.get(raw_device_id, _truncate_identifier(raw_device_id))
        return rows
    if table_name == "models":
        rows = _fetch_all_paginated(api.fetch_models, sort_by=sort_by, sort_desc=sort_desc)
        return [_normalize_model_row(item) for item in rows]
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


@app.route("/health")
def health_check() -> tuple[Response, int]:
    return (
        jsonify(
            {
                "status": "healthy",
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
            {"name": "Models", "count": api.count_models(), "endpoint": "view_models"},
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
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("timestamp", True)
    token_history = request.args.get("token_history", "")
    try:
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
            )
        else:
            page = _get_page()
            token_history = request.args.get("token_history", "")
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
            )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/devices")
def view_devices() -> str:
    device_id = request.args.get("device_id") or None
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("device_id", False)
    token_history = request.args.get("token_history", "")
    try:
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
        )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/heartbeats")
def view_heartbeats() -> str:
    sort_by, sort_desc = _get_sort("timestamp", True)
    try:
        response = api.fetch_heartbeats()
        device_names = _device_display_names()
        items = [_normalize_heartbeat_row(item) for item in response.get("items", [])]
        for item in items:
            raw_device_id = str(item.get("device_id") or "")
            item["_device_id_raw"] = raw_device_id
            item["device_id"] = device_names.get(raw_device_id, _truncate_identifier(raw_device_id))
        context = _table_context(
            title="Heartbeats",
            description="Latest heartbeat per device.",
            endpoint="view_heartbeats",
            rows=items,
            columns=HEARTBEAT_COLUMNS,
            sort_by=sort_by,
            sort_desc=sort_desc,
            pagination={},
            filters=[],
            count=len(items),
            total_count=len(items),
            export_url=_build_export_url("heartbeats"),
        )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/models")
def view_models() -> str:
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("timestamp", True)
    token_history = request.args.get("token_history", "")
    try:
        response = api.fetch_models(
            limit=limit,
            next_token=request.args.get("next_token"),
            sort_by=sort_by,
            sort_desc=sort_desc,
        )
        rows = [_normalize_model_row(item) for item in response.get("items", [])]
        for row in rows:
            bundle = _model_bundle_metadata(row)
            if bundle:
                row["bundle_uploaded_at"] = bundle.get("bundle_uploaded_at")
                row["model_sha256"] = _short_hash(str(bundle.get("model_sha256", "")))
                row["labels_sha256"] = _short_hash(str(bundle.get("labels_sha256", "")))
        return render_template(
            "models.html",
            title="Models",
            description="Model registry plus bundle metadata. Upload/delete stays here.",
            rows=rows,
            columns=_visible_columns(MODEL_COLUMNS, rows),
            sort_by=sort_by,
            sort_desc=sort_desc,
            sort_urls=_build_sort_urls(_visible_columns(MODEL_COLUMNS, rows), "view_models", sort_by, sort_desc),
            pagination=_token_pagination(response.get("next_token"), "view_models", page, token_history),
            total_count=api.count_models(),
            count=response.get("count", len(rows)),
            web_read_only=WEB_READ_ONLY,
            export_url=_build_export_url("models"),
        )
    except Exception as exc:
        return render_template("models.html", rows=[], columns=MODEL_COLUMNS, error=str(exc), sort_urls={}, pagination={})


@app.route("/videos")
def view_videos() -> str:
    device_id = request.args.get("device_id") or None
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
            )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/deployments")
def view_deployments() -> str:
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
        context = _table_context(
            title="Deployments",
            description="Deployment records plus linked device assignments.",
            endpoint="view_deployments",
            rows=rows,
            columns=DEPLOYMENT_COLUMNS,
            sort_by=sort_by,
            sort_desc=sort_desc,
            pagination=_token_pagination(response.get("next_token"), "view_deployments", page, token_history),
            filters=[{"name": "limit", "label": "Rows", "value": str(limit), "options": ["25", "50", "100", "200"]}],
            count=len(rows),
            total_count=_count_deployments(),
            export_url=_build_export_url("deployments"),
        )
        return render_template("table.html", **context)
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/environment")
def view_environment() -> str:
    device_id = request.args.get("device_id") or None
    limit = _get_limit()
    page = _get_page()
    sort_by, sort_desc = _get_sort("timestamp", True)
    token_history = request.args.get("token_history", "")
    try:
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
    return render_template("add_model.html")


@app.route("/add_model", methods=["POST"])
def add_model_submit() -> Any:
    if WEB_READ_ONLY:
        return render_template("error.html", error="Model management is disabled in read-only mode"), 403
    uploaded_bundle = False
    model_id = request.form.get("model_id", "")
    try:
        model_data = {
            "model_id": request.form["model_id"],
            "name": request.form["name"],
            "version": request.form["version"],
            "description": request.form.get("description", ""),
        }
        metadata = request.form.get("metadata")
        if metadata:
            model_data["metadata"] = json.loads(metadata)

        bundle_metadata = upload_model_bundle(
            model_data["model_id"],
            request.files.get("model_file"),
            request.files.get("labels_file"),
        )
        uploaded_bundle = True
        merged_metadata = dict(model_data.get("metadata") or {})
        merged_metadata["bundle"] = bundle_metadata
        model_data["metadata"] = merged_metadata
        api.create_model(model_data)
        return redirect(url_for("view_models"))
    except Exception as exc:
        if uploaded_bundle and model_id:
            try:
                delete_model_bundle(model_id)
            except Exception:
                pass
        return render_template("add_model.html", error=str(exc))


@app.route("/models/<model_id>/delete", methods=["POST"])
def delete_model(model_id: str) -> Any:
    if WEB_READ_ONLY:
        return render_template("error.html", error="Model deletion is disabled in read-only mode"), 403
    try:
        delete_model_bundle(model_id)
        api.delete_model(model_id)
        return redirect(url_for("view_models"))
    except Exception as exc:
        response = api.fetch_models(limit=DEFAULT_PAGE_LIMIT, sort_by="timestamp", sort_desc=True)
        rows = [_normalize_model_row(item) for item in response.get("items", [])]
        return render_template(
            "models.html",
            rows=rows,
            columns=_visible_columns(MODEL_COLUMNS, rows),
            error=str(exc),
            sort_urls={},
            pagination={},
            total_count=api.count_models(),
            count=response.get("count", len(rows)),
            web_read_only=WEB_READ_ONLY,
        )


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
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        dynamodb = boto3.resource(
            "dynamodb",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
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
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": VIDEOS_BUCKET, "Key": key},
            ExpiresIn=3600,
        )
        return jsonify({"url": url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
