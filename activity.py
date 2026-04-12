from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key
from pydantic import BaseModel, Field


ACTIVITY_RETENTION_DAYS = 30
BUGCAM_LOG_PATTERN = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2}) \| (?P<level>[A-Z]+)\s+\| (?P<message>.*)$")


class ActivitySource(str, Enum):
    DASHBOARD = "dashboard"
    BACKEND = "backend"
    S3_TRIGGER = "s3_trigger"
    BUGCAM = "bugcam"


class ActivityEventType(str, Enum):
    API_REQUEST = "api_request"
    DEVICE_SETUP = "device_setup"
    UPLOAD_URL_REQUESTED = "upload_url_requested"
    S3_LIST = "s3_list"
    S3_OPEN = "s3_open"
    S3_OBJECT_PROCESSED = "s3_object_processed"
    S3_OBJECT_SEEN = "s3_object_seen"
    BUGCAM_LOG = "bugcam_log"


class ActivityEvent(BaseModel):
    timestamp: datetime
    source: ActivitySource
    event_type: ActivityEventType
    message: str
    actor_type: str = "system"
    device_id: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    status_code: Optional[int] = None
    s3_bucket: Optional[str] = None
    s3_key: Optional[str] = None
    level: Optional[str] = None
    metadata: Dict[str, str] = Field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def event_message(method: str, path: str, status_code: int) -> str:
    return f"{method} {path} -> {status_code}"


def activity_item(event: ActivityEvent) -> Dict[str, Any]:
    timestamp = event.timestamp.astimezone(timezone.utc)
    item = event.model_dump(mode="json", exclude_none=True)
    item["event_date"] = timestamp.date().isoformat()
    item["timestamp_event_id"] = f"{timestamp.isoformat()}#{uuid.uuid4().hex}"
    item["ttl"] = int((timestamp + timedelta(days=ACTIVITY_RETENTION_DAYS)).timestamp())
    return item


def record_activity_event(table: Any, event: ActivityEvent) -> None:
    table.put_item(Item=activity_item(event))


def _query_day(table: Any, day: datetime, limit: int) -> List[Dict[str, Any]]:
    response = table.query(
        KeyConditionExpression=Key("event_date").eq(day.date().isoformat()),
        ScanIndexForward=False,
        Limit=limit,
    )
    return list(response.get("Items", []))


def _matches(item: Dict[str, Any], source: str, device_id: str, query: str) -> bool:
    text = f"{item.get('message', '')} {item.get('s3_key', '')} {item.get('path', '')}".lower()
    return (
        (not source or item.get("source") == source)
        and (not device_id or item.get("device_id") == device_id)
        and (not query or query.lower() in text)
    )


def list_activity_events(table: Any, source: str, device_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    today = utc_now()
    for offset in range(ACTIVITY_RETENTION_DAYS):
        for item in _query_day(table, today - timedelta(days=offset), limit):
            if _matches(item, source, device_id, query):
                rows.append(item)
            if len(rows) >= limit:
                return rows
    return rows


def s3_object_event(bucket: str, item: Dict[str, Any]) -> ActivityEvent:
    modified = item["LastModified"].astimezone(timezone.utc)
    key = str(item["Key"])
    return ActivityEvent(
        timestamp=modified,
        source=ActivitySource.S3_TRIGGER,
        event_type=ActivityEventType.S3_OBJECT_SEEN,
        message=f"S3 object updated: {key}",
        s3_bucket=bucket,
        s3_key=key,
        device_id=device_id_from_key(key),
        metadata={"size": str(item.get("Size", 0))},
    )


def device_id_from_key(key: str) -> Optional[str]:
    parts = key.split("/", 3)
    if len(parts) >= 3 and parts[0] == "v1":
        return parts[1]
    return None


def bugcam_log_events(bucket: str, key: str, body: str, modified: datetime) -> List[ActivityEvent]:
    return [bugcam_log_event(bucket, key, line, modified) for line in body.splitlines() if line.strip()]


def bugcam_log_event(bucket: str, key: str, line: str, modified: datetime) -> ActivityEvent:
    match = BUGCAM_LOG_PATTERN.match(line)
    timestamp = _bugcam_log_timestamp(modified, match.group("time")) if match else modified
    return ActivityEvent(
        timestamp=timestamp,
        source=ActivitySource.BUGCAM,
        event_type=ActivityEventType.BUGCAM_LOG,
        message=match.group("message") if match else line,
        level=match.group("level") if match else "INFO",
        s3_bucket=bucket,
        s3_key=key,
        device_id=device_id_from_key(key),
    )


def _bugcam_log_timestamp(modified: datetime, time_value: str) -> datetime:
    hour, minute, second = (int(part) for part in time_value.split(":"))
    return modified.astimezone(timezone.utc).replace(hour=hour, minute=minute, second=second, microsecond=0)
