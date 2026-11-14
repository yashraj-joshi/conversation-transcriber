"""HTTP API Lambda (API Gateway v2 payload 2.0). Every route sits behind a Cognito JWT authorizer."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import core

log = logging.getLogger()
log.setLevel(logging.INFO)

PRESIGN_EXPIRES = 900  # 15 minutes


@dataclass
class Deps:
    s3: Any
    bucket: str
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


class HttpError(Exception):
    def __init__(self, status: int, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra or {}


def _response(status: int, body: dict):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def _body(event) -> dict:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw or "{}")
    except ValueError as exc:
        raise core.ValidationError("body must be JSON") from exc
    if not isinstance(data, dict):
        raise core.ValidationError("body must be a JSON object")
    return data


def _claims(event) -> dict:
    return (event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})) or {}


def _missing(exc) -> bool:
    code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
    return code in ("NoSuchKey", "404", "NotFound")


def _list_keys(deps: Deps, prefix: str):
    token = None
    while True:
        kwargs = {"Bucket": deps.bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = deps.s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            yield obj
        if not page.get("IsTruncated"):
            return
        token = page.get("NextContinuationToken")


def _read_json(deps: Deps, key: str):
    try:
        obj = deps.s3.get_object(Bucket=deps.bucket, Key=key)
    except Exception as exc:
        if _missing(exc):
            return None
        raise
    return json.loads(obj["Body"].read().decode("utf-8"))


# --- Routes ----------------------------------------------------------------------------------------

def create_upload(deps: Deps, event):
    req = core.validate_upload_request(_body(event))
    post = deps.s3.generate_presigned_post(
        Bucket=deps.bucket,
        Key=req["key"],
        Fields={"Content-Type": req["contentType"]},
        Conditions=[
            {"Content-Type": req["contentType"]},
            ["content-length-range", 1, core.MAX_PART_BYTES],
        ],
        ExpiresIn=PRESIGN_EXPIRES,
    )
    return 200, {"url": post["url"], "fields": post["fields"], "key": req["key"],
                 "maxBytes": core.MAX_PART_BYTES}


def complete_recording(deps: Deps, event):
    rid = core.validate_recording_id((event.get("pathParameters") or {}).get("id"))
    now = deps.now()
    req = core.validate_complete_request(_body(event), now)

    status = _read_json(deps, core.status_key(rid))
    if status and status.get("state") == "done":
        return 200, status

    keys = [o["Key"] for o in _list_keys(deps, f"audio/{rid}/part-")]
    parts, missing = core.match_parts(keys, req["partCount"])
    if missing:
        raise HttpError(409, "some audio parts have not been uploaded", {"missing": missing})

    sub = str(_claims(event).get("sub", "unknown"))
    manifest = core.build_manifest(rid, req, parts, sub, now)
    deps.s3.put_object(Bucket=deps.bucket, Key=core.manifest_key(rid),
                       Body=json.dumps(manifest).encode("utf-8"), ContentType="application/json")
    return 202, {"recordingId": rid, "state": "transcribing", "updatedAt": core.iso_now(now)}


def get_status(deps: Deps, event):
    rid = core.validate_recording_id((event.get("pathParameters") or {}).get("id"))
    status = _read_json(deps, core.status_key(rid))
    return 200, status or {"recordingId": rid, "state": "pending"}


def list_months(deps: Deps, event):
    months, token = set(), None
    while True:
        kwargs = {"Bucket": deps.bucket, "Prefix": "transcripts/", "Delimiter": "/"}
        if token:
            kwargs["ContinuationToken"] = token
        page = deps.s3.list_objects_v2(**kwargs)
        for cp in page.get("CommonPrefixes", []):
            name = cp["Prefix"][len("transcripts/"):].rstrip("/")
            try:
                months.add(core.validate_month(name))
            except core.ValidationError:
                continue
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
    return 200, {"months": core.sort_newest_first(months)}


def _header_fields(deps: Deps, key: str) -> dict:
    """Parse the transcript header from its first few KB (spec 004 D2)."""
    try:
        obj = deps.s3.get_object(Bucket=deps.bucket, Key=key, Range=f"bytes=0-{core.HEADER_READ_BYTES - 1}")
        return core.parse_header(obj["Body"].read().decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001 - a missing title never breaks the list
        log.warning("could not read header of %s", key)
        return {}


def _with_titles(deps: Deps, items: list) -> list:
    if not items:
        return items
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        headers = list(pool.map(lambda i: _header_fields(deps, i["key"]), items))
    for item, fields in zip(items, headers):
        item["title"] = core.display_title(fields)
        item["summary"] = fields.get(core.SUMMARY_FIELD) or None
    return items


def list_transcripts(deps: Deps, event):
    month = core.validate_month((event.get("queryStringParameters") or {}).get("month"))
    items = []
    for obj in _list_keys(deps, f"transcripts/{month}/"):
        item = core.transcript_item(obj["Key"], obj.get("Size", 0))
        if item:
            items.append(item)
    items.sort(key=lambda i: i["name"], reverse=True)
    return 200, {"month": month, "items": _with_titles(deps, items)}


def get_transcript(deps: Deps, event):
    key = core.validate_readable_key((event.get("queryStringParameters") or {}).get("key"))
    try:
        obj = deps.s3.get_object(Bucket=deps.bucket, Key=key)
    except Exception as exc:
        if _missing(exc):
            raise HttpError(404, "transcript not found") from exc
        raise
    return 200, {"key": key, "text": obj["Body"].read().decode("utf-8", "replace")}


def _exists(deps: Deps, key: str) -> bool:
    try:
        deps.s3.head_object(Bucket=deps.bucket, Key=key)
        return True
    except Exception as exc:
        if _missing(exc):
            return False
        raise


def _delete_prefix(deps: Deps, prefix: str) -> int:
    keys = [o["Key"] for o in _list_keys(deps, prefix)]
    for i in range(0, len(keys), 1000):
        deps.s3.delete_objects(Bucket=deps.bucket,
                               Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})
    return len(keys)


def delete_transcript(deps: Deps, event):
    key = core.validate_transcript_key(_body(event).get("key"))
    try:
        head = deps.s3.head_object(Bucket=deps.bucket, Key=key)
    except Exception as exc:
        if _missing(exc):
            raise HttpError(404, "transcript not found") from exc
        raise
    trash = core.trash_key(key)
    deps.s3.copy_object(Bucket=deps.bucket, Key=trash, CopySource={"Bucket": deps.bucket, "Key": key},
                        MetadataDirective="COPY")
    deps.s3.delete_object(Bucket=deps.bucket, Key=key)
    rid = (head.get("Metadata") or {}).get("recording-id")
    removed = 0
    try:
        rid = core.validate_recording_id(rid)
        removed = _delete_prefix(deps, f"audio/{rid}/") + _delete_prefix(deps, f"work/{rid}/")
    except core.ValidationError:
        rid = None
    now = deps.now()
    return 200, {"key": trash, "recordingId": rid, "removedAudioObjects": removed,
                 "deletedAt": core.iso_now(now), "purgeAt": core.iso_now(core.purge_date(now))}


def list_deleted(deps: Deps, event):
    items = []
    for obj in _list_keys(deps, "trash/transcripts/"):
        try:
            original = core.original_key(obj["Key"])
        except core.ValidationError:
            continue
        item = core.transcript_item(original, obj.get("Size", 0))
        deleted = obj.get("LastModified") or deps.now()
        if isinstance(deleted, str):
            deleted = core.parse_started_at(deleted)
        item.update({"key": obj["Key"], "originalKey": original,
                     "deletedAt": core.iso_now(deleted), "purgeAt": core.iso_now(core.purge_date(deleted))})
        items.append(item)
    items.sort(key=lambda i: i["deletedAt"], reverse=True)
    return 200, {"items": _with_titles(deps, items)}


def restore_transcript(deps: Deps, event):
    trash = core.validate_trash_key(_body(event).get("key"))
    original = core.original_key(trash)
    if not _exists(deps, trash):
        raise HttpError(404, "deleted transcript not found")
    if _exists(deps, original):
        raise HttpError(409, "a transcript with the same name already exists")
    deps.s3.copy_object(Bucket=deps.bucket, Key=original, CopySource={"Bucket": deps.bucket, "Key": trash},
                        MetadataDirective="COPY")
    deps.s3.delete_object(Bucket=deps.bucket, Key=trash)
    return 200, {"key": original}


ROUTES = {
    "POST /uploads": create_upload,
    "POST /recordings/{id}/complete": complete_recording,
    "GET /recordings/{id}": get_status,
    "GET /transcripts/months": list_months,
    "GET /transcripts": list_transcripts,
    "GET /transcript": get_transcript,
    "POST /transcripts/delete": delete_transcript,
    "GET /transcripts/deleted": list_deleted,
    "POST /transcripts/restore": restore_transcript,
}


def _default_deps() -> Deps:
    import boto3
    from botocore.config import Config

    s3 = boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
    return Deps(s3=s3, bucket=os.environ["DATA_BUCKET"])


_deps = None


def handler(event, context, deps: Deps | None = None):
    global _deps
    if deps is None:
        _deps = _deps or _default_deps()
        deps = _deps
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return _response(404, {"error": "not found"})
    try:
        status, body = route(deps, event)
        return _response(status, body)
    except core.ValidationError as exc:
        return _response(400, {"error": str(exc)})
    except HttpError as exc:
        return _response(exc.status, {"error": exc.message, **exc.extra})
    except Exception:  # noqa: BLE001
        log.exception("unhandled error on %s", event.get("routeKey"))
        return _response(500, {"error": "internal error"})
