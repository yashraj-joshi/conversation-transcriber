"""S3-event Lambda: audio/<id>/manifest.json -> OpenRouter -> transcripts/YYYY-MM/<name>.txt.

Idempotent: a recording whose status is `done` is skipped. Each part's text is cached under work/ so a
Retry never re-bills a part that already succeeded (spec 002 FR-010).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import core
from openrouter_client import OpenRouterClient, OpenRouterError

log = logging.getLogger()
log.setLevel(logging.INFO)


@dataclass
class Config:
    bucket: str
    model_param: str
    api_key_param: str
    vocabulary_key: str
    data_collection: str = "deny"
    parallelism: int = 4
    diarize: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            bucket=os.environ["DATA_BUCKET"],
            model_param=os.environ["MODEL_PARAM"],
            api_key_param=os.environ["API_KEY_PARAM"],
            vocabulary_key=os.environ.get("VOCABULARY_KEY", "config/vocabulary.txt"),
            data_collection=os.environ.get("DATA_COLLECTION", "deny"),
            parallelism=max(1, int(os.environ.get("TRANSCRIBE_PARALLELISM", "4"))),
            diarize=os.environ.get("DIARIZE", "false").strip().lower() in ("1", "true", "yes"),
        )


@dataclass
class Deps:
    s3: Any
    ssm: Any
    client_factory: Callable[[str], Any]
    config: Config
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


_api_key_cache: dict = {}


def _error_code(exc) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def _is_missing(exc) -> bool:
    return _error_code(exc) in ("NoSuchKey", "404", "NotFound")


def get_json(s3, bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except Exception as exc:  # botocore ClientError (duck-typed so tests need no boto3)
        if _is_missing(exc):
            return None
        raise
    return json.loads(obj["Body"].read().decode("utf-8"))


def put_json(s3, bucket, key, data):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(data).encode("utf-8"),
                  ContentType="application/json")


def write_status(deps: Deps, rid: str, state: str, **extra):
    status = {"recordingId": rid, "state": state, "updatedAt": core.iso_now(deps.now())}
    status.update({k: v for k, v in extra.items() if v is not None})
    put_json(deps.s3, deps.config.bucket, core.status_key(rid), status)


def load_model(deps: Deps) -> str:
    value = deps.ssm.get_parameter(Name=deps.config.model_param)["Parameter"]["Value"].strip()
    if not value:
        raise core.ValidationError("transcription model parameter is empty")
    return value


API_KEY_TTL_SECONDS = 600


def load_api_key(deps: Deps) -> str:
    """Read the key from SSM, cached per container for 10 minutes so a rotated key is picked up."""
    name = deps.config.api_key_param
    cached = _api_key_cache.get(name)
    now = time.monotonic()
    if cached and now - cached[1] < API_KEY_TTL_SECONDS:
        return cached[0]
    value = deps.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"].strip()
    if not value or value == "REPLACE_ME":
        raise OpenRouterError(401, "the stored key is still the placeholder value")
    _api_key_cache[name] = (value, now)
    return value


def load_vocabulary(deps: Deps):
    try:
        obj = deps.s3.get_object(Bucket=deps.config.bucket, Key=deps.config.vocabulary_key)
    except Exception as exc:
        if _is_missing(exc):
            log.info("no vocabulary file at %s", deps.config.vocabulary_key)
            return []
        raise
    terms, skipped = core.parse_vocabulary(obj["Body"].read().decode("utf-8", "replace"))
    for term, reason in skipped:
        log.warning("vocabulary term skipped (%s): %s", reason, term[:120])
    return terms


def transcribe_part(deps: Deps, client, rid: str, part: dict, model: str, keyterms) -> dict:
    cache_key = core.work_key(rid, part["index"])
    cached = get_json(deps.s3, deps.config.bucket, cache_key)
    if (cached and "text" in cached and cached.get("model") == model
            and cached.get("diarizeRequested", False) == deps.config.diarize):
        log.info("part %s: using cached result", part["index"])
        return cached

    audio = deps.s3.get_object(Bucket=deps.config.bucket, Key=part["key"])["Body"].read()
    if not audio or len(audio) > core.MAX_PART_BYTES:
        raise core.ValidationError(f"part {part['index']} has invalid size {len(audio)}")
    fmt = part["key"].rsplit(".", 1)[1]
    audio_b64 = base64.b64encode(audio).decode("ascii")

    vocab_applied = bool(keyterms)
    diarized = deps.config.diarize
    payload = core.build_transcription_request(model, audio_b64, fmt, keyterms, deps.config.data_collection,
                                               diarize=diarized)
    try:
        result = client.transcribe(payload)
    except OpenRouterError as exc:
        if exc.status != 400:
            raise
        # A 400 may be caused by an optional feature. Drop them one at a time so a transcript is never
        # lost because of the vocabulary (FR-006) or speaker labels (FR-015).
        last = exc
        result = None
        for feature in ("vocabulary", "speakers"):
            if feature == "vocabulary" and vocab_applied:
                payload = {k: v for k, v in payload.items() if k != "keyterms"}
                vocab_applied = False
            elif feature == "speakers" and diarized:
                payload = core.drop_diarization(payload)
                diarized = False
            else:
                continue
            log.warning("part %s: rejected (%s); retrying without %s", part["index"], last.message[:200], feature)
            try:
                result = client.transcribe(payload)
                break
            except OpenRouterError as again:
                if again.status != 400:
                    raise
                last = again
        if result is None:
            raise last

    usage = result.get("usage") or {}
    segments = core.compact_segments(result.get("segments")) if diarized else []
    record = {
        "index": part["index"],
        "model": model,
        "text": result.get("text") or "",
        "segments": segments,
        "speakersLabelled": any(seg.get("speaker") for seg in segments),
        "diarizeRequested": deps.config.diarize,
        "cost": usage.get("cost"),
        "seconds": usage.get("seconds"),
        "vocabularyApplied": vocab_applied,
    }
    put_json(deps.s3, deps.config.bucket, cache_key, record)
    return record


def process_manifest(deps: Deps, key: str):
    rid = core.recording_id_from_manifest_key(key)
    status = get_json(deps.s3, deps.config.bucket, core.status_key(rid))
    if status and status.get("state") == "done":
        log.info("recording %s already done; skipping", rid)
        return status

    model = "(unknown)"
    try:
        meta = core.validate_manifest(get_json(deps.s3, deps.config.bucket, key))
        write_status(deps, rid, "transcribing")
        model = load_model(deps)
        client = deps.client_factory(load_api_key(deps))
        keyterms = load_vocabulary(deps)
        log.info("recording %s: %d parts, model=%s, keyterms=%d",
                 rid, len(meta["parts"]), model, len(keyterms))

        workers = min(deps.config.parallelism, len(meta["parts"]))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda p: transcribe_part(deps, client, rid, p, model, keyterms), meta["parts"]
            ))

        costs = [r["cost"] for r in results if isinstance(r.get("cost"), (int, float))]
        total_cost = sum(costs) if costs else None
        vocab = core.vocabulary_status(len(keyterms), [r["vocabularyApplied"] for r in results])
        speakers = core.speakers_status(deps.config.diarize, [r.get("speakersLabelled") for r in results])
        bodies = [core.part_body(r, r["index"]) for r in results]
        text = core.render_transcript(meta, bodies, model, vocab, total_cost, speakers)
        out_key = core.transcript_key(rid, meta["startedAt"], meta["tzOffsetMinutes"])
        deps.s3.put_object(
            Bucket=deps.config.bucket, Key=out_key, Body=text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            Metadata={
                "recording-id": rid,
                "started-at": meta["startedAt"].isoformat(),
                "duration-seconds": str(int(meta["durationSeconds"])),
                "model": model[:200],
            },
        )
        write_status(deps, rid, "done", transcriptKey=out_key, model=model, cost=total_cost,
                     vocabulary=vocab)
        log.info("recording %s: wrote %s", rid, out_key)
        return {"state": "done", "transcriptKey": out_key}
    except OpenRouterError as exc:
        if exc.status == 401:
            _api_key_cache.clear()  # re-read the key on the next attempt
        message = core.error_message(exc.status, exc.message, model)
    except core.ValidationError as exc:
        message = f"Invalid recording: {exc}"
    except Exception as exc:  # noqa: BLE001 - report every failure as a status, never crash silently
        log.exception("recording %s failed", rid)
        message = f"Internal error: {type(exc).__name__}"
    log.error("recording %s failed: %s", rid, message)
    write_status(deps, rid, "failed", error=message, model=model)
    return {"state": "failed", "error": message}


def _default_deps() -> Deps:
    import boto3  # bundled in the Lambda runtime; imported lazily so tests need no AWS SDK

    return Deps(
        s3=boto3.client("s3"),
        ssm=boto3.client("ssm"),
        client_factory=lambda key: OpenRouterClient(key, app_title="Conversation Transcriber"),
        config=Config.from_env(),
    )


_deps = None


def handler(event, context, deps: Deps | None = None):
    global _deps
    if deps is None:
        _deps = _deps or _default_deps()
        deps = _deps
    results = []
    for record in event.get("Records", []):
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        if key.endswith("/manifest.json"):
            results.append(process_manifest(deps, key))
    return {"results": results}
