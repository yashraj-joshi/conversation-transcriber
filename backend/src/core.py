"""Pure business logic: storage keys, time bucketing, validation, vocabulary, request building.

Nothing in this module talks to AWS or the network, so it is unit-tested offline (Constitution VI).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

# --- Limits (spec 002 FR-008; plan R3) -------------------------------------------------------------

PART_SECONDS = 300                       # 5 minutes of audio per part
MAX_PARTS = 36                           # 3 hours
MAX_DURATION_SECONDS = 10800             # 3 hours
MAX_PART_BYTES = 18 * 1024 * 1024        # 18 MB raw -> 24 MB base64 (< 25 MB OpenRouter inline cap)
MAX_TITLE_LENGTH = 120
MAX_SOURCE_NAME_LENGTH = 200
MAX_FUTURE_SKEW = timedelta(minutes=10)

MAX_KEYTERMS = 1000                      # OpenRouter `keyterms` limits
MAX_KEYTERM_LENGTH = 100

# Formats MAI-Transcribe 2 accepts (WAV, MP3, FLAC). The browser always records WAV.
CONTENT_TYPES = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/flac": "flac",
}
EXT_CONTENT_TYPE = {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac"}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_TRANSCRIPT_KEY_RE = re.compile(
    r"^transcripts/(\d{4}-\d{2})/(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})_([0-9a-f]{8})\.txt$"
)
_PART_KEY_RE = re.compile(r"^audio/[0-9a-f-]{36}/part-(\d{3})\.(wav|mp3|flac)$")


class ValidationError(ValueError):
    """Invalid client input. The message is safe to return to the caller."""


# --- Keys ------------------------------------------------------------------------------------------

def validate_recording_id(value) -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise ValidationError("recordingId must be a lowercase UUID v4")
    return value


def audio_extension(content_type) -> str:
    if not isinstance(content_type, str):
        raise ValidationError("contentType is required")
    base = content_type.split(";", 1)[0].strip().lower()
    if base not in CONTENT_TYPES:
        raise ValidationError("contentType must be one of: " + ", ".join(sorted(CONTENT_TYPES)))
    return CONTENT_TYPES[base]


def part_key(recording_id: str, index: int, ext: str) -> str:
    return f"audio/{recording_id}/part-{index:03d}.{ext}"


def parse_part_key(key: str):
    """Return (index, ext) for an audio part key, or None if the key is not a part."""
    m = _PART_KEY_RE.match(key)
    return (int(m.group(1)), m.group(2)) if m else None


def manifest_key(recording_id: str) -> str:
    return f"audio/{recording_id}/manifest.json"


def status_key(recording_id: str) -> str:
    return f"status/{recording_id}.json"


def work_key(recording_id: str, index: int) -> str:
    return f"work/{recording_id}/part-{index:03d}.json"


def recording_id_from_manifest_key(key: str) -> str:
    m = re.match(r"^audio/([0-9a-f-]{36})/manifest\.json$", key)
    if not m:
        raise ValidationError(f"not a manifest key: {key}")
    return validate_recording_id(m.group(1))


# --- Time ------------------------------------------------------------------------------------------

def parse_started_at(value) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("startedAt must be an ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError("startedAt must be an ISO-8601 string") from exc
    if dt.tzinfo is None:
        raise ValidationError("startedAt must include a time zone (use UTC 'Z')")
    return dt.astimezone(timezone.utc)


def local_start(started_at: datetime, tz_offset_minutes: int) -> datetime:
    """Recording start in the device's local time (naive datetime)."""
    return (started_at + timedelta(minutes=tz_offset_minutes)).replace(tzinfo=None)


def transcript_key(recording_id: str, started_at: datetime, tz_offset_minutes: int) -> str:
    local = local_start(started_at, tz_offset_minutes)
    return (
        f"transcripts/{local:%Y-%m}/{local:%Y-%m-%d_%H-%M-%S}_{recording_id.replace('-', '')[:8]}.txt"
    )


def format_offset(tz_offset_minutes: int) -> str:
    sign = "+" if tz_offset_minutes >= 0 else "-"
    total = abs(tz_offset_minutes)
    return f"UTC{sign}{total // 60:02d}:{total % 60:02d}"


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def iso_now(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --- Request validation ----------------------------------------------------------------------------

def _int(value, name, lo, hi) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer")
    if not lo <= value <= hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}")
    return value


def validate_upload_request(body) -> dict:
    if not isinstance(body, dict):
        raise ValidationError("JSON object body required")
    rid = validate_recording_id(body.get("recordingId"))
    index = _int(body.get("index"), "index", 0, MAX_PARTS - 1)
    content_type = body.get("contentType")
    ext = audio_extension(content_type)
    return {
        "recordingId": rid,
        "index": index,
        "contentType": EXT_CONTENT_TYPE[ext],
        "key": part_key(rid, index, ext),
    }


def validate_complete_request(body, now: datetime) -> dict:
    if not isinstance(body, dict):
        raise ValidationError("JSON object body required")
    started = parse_started_at(body.get("startedAt"))
    if started > now + MAX_FUTURE_SKEW:
        raise ValidationError("startedAt is in the future")
    tz = _int(body.get("tzOffsetMinutes"), "tzOffsetMinutes", -840, 840)
    duration = body.get("durationSeconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValidationError("durationSeconds must be a number")
    if not 1 <= duration <= MAX_DURATION_SECONDS:
        raise ValidationError(f"durationSeconds must be between 1 and {MAX_DURATION_SECONDS}")
    part_count = _int(body.get("partCount"), "partCount", 1, MAX_PARTS)
    title = body.get("title")
    if title is not None:
        if not isinstance(title, str):
            raise ValidationError("title must be a string")
        title = " ".join(title.split())
        if len(title) > MAX_TITLE_LENGTH:
            raise ValidationError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        title = title or None
    source = body.get("sourceName")
    if source is not None:
        if not isinstance(source, str):
            raise ValidationError("sourceName must be a string")
        source = source.replace("\\", "/").rsplit("/", 1)[-1]          # base name only
        source = " ".join("".join(c for c in source if c.isprintable()).split())
        if len(source) > MAX_SOURCE_NAME_LENGTH:
            raise ValidationError(f"sourceName must be at most {MAX_SOURCE_NAME_LENGTH} characters")
        source = source or None
    return {
        "startedAt": started.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "tzOffsetMinutes": tz,
        "durationSeconds": float(duration),
        "partCount": part_count,
        "title": title,
        "sourceName": source,
    }


def match_parts(keys, part_count: int):
    """Pick one stored part per index 0..part_count-1. Returns (parts, missing_indices)."""
    found = {}
    for key in keys:
        parsed = parse_part_key(key)
        if parsed and parsed[0] < part_count:
            found.setdefault(parsed[0], (key, parsed[1]))
    parts = [
        {"index": i, "key": found[i][0], "contentType": EXT_CONTENT_TYPE[found[i][1]]}
        for i in range(part_count)
        if i in found
    ]
    missing = [i for i in range(part_count) if i not in found]
    return parts, missing


def build_manifest(recording_id: str, req: dict, parts: list, submitted_by: str, now: datetime) -> dict:
    return {
        "recordingId": recording_id,
        "startedAt": req["startedAt"],
        "tzOffsetMinutes": req["tzOffsetMinutes"],
        "durationSeconds": req["durationSeconds"],
        "partCount": req["partCount"],
        "parts": parts,
        "title": req["title"],
        "sourceName": req.get("sourceName"),
        "submittedBy": submitted_by,
        "submittedAt": iso_now(now),
    }


def validate_manifest(manifest) -> dict:
    if not isinstance(manifest, dict):
        raise ValidationError("manifest must be an object")
    rid = validate_recording_id(manifest.get("recordingId"))
    started = parse_started_at(manifest.get("startedAt"))
    tz = _int(manifest.get("tzOffsetMinutes"), "tzOffsetMinutes", -840, 840)
    count = _int(manifest.get("partCount"), "partCount", 1, MAX_PARTS)
    parts = manifest.get("parts")
    if not isinstance(parts, list) or len(parts) != count:
        raise ValidationError("parts must list exactly partCount entries")
    ordered = sorted(parts, key=lambda p: p.get("index", -1))
    for expected, part in enumerate(ordered):
        parsed = parse_part_key(part.get("key", ""))
        if part.get("index") != expected or not parsed or parsed[0] != expected:
            raise ValidationError(f"part {expected} is missing or malformed")
        if not part["key"].startswith(f"audio/{rid}/"):
            raise ValidationError("part key does not belong to this recording")
    return {
        "recordingId": rid,
        "startedAt": started,
        "tzOffsetMinutes": tz,
        "durationSeconds": float(manifest.get("durationSeconds") or 0),
        "title": manifest.get("title"),
        "sourceName": manifest.get("sourceName"),
        "parts": ordered,
    }


# --- Vocabulary (spec 002 FR-004, FR-005) ----------------------------------------------------------

def parse_vocabulary(text: str):
    """Parse the vocabulary file. Returns (terms, skipped) where skipped is a list of (term, reason)."""
    terms, skipped, seen = [], [], set()
    for raw in (text or "").splitlines():
        term = " ".join(raw.split())
        if not term or term.startswith("#"):
            continue
        folded = term.casefold()
        if folded in seen:
            skipped.append((term, "duplicate"))
            continue
        if len(term) > MAX_KEYTERM_LENGTH:
            skipped.append((term, f"longer than {MAX_KEYTERM_LENGTH} characters"))
            continue
        if len(terms) >= MAX_KEYTERMS:
            skipped.append((term, f"over the {MAX_KEYTERMS}-term limit"))
            continue
        seen.add(folded)
        terms.append(term)
    return terms, skipped


# --- OpenRouter request / response (plan R1, R7) ---------------------------------------------------

def build_transcription_request(model: str, audio_b64: str, audio_format: str, keyterms, data_collection,
                                diarize: bool = False, keyterms_field: bool = True):
    """OpenRouter STT request. The vocabulary goes out twice: as OpenRouter's generic `keyterms` (unless
    the model is known to reject that field) and as Azure's native `phraseList`. Provider options are only
    forwarded to the provider that serves the request, so the second form is harmless elsewhere."""
    if not model or not isinstance(model, str):
        raise ValidationError("transcription model is not configured")
    payload = {
        "model": model.strip(),
        "input_audio": {"data": audio_b64, "format": audio_format},
        "response_format": "json",
    }
    provider = {}
    if data_collection in ("deny", "allow"):
        provider["data_collection"] = data_collection
    azure = {}
    if keyterms:
        if keyterms_field:
            payload["keyterms"] = list(keyterms)
        azure["phraseList"] = {"phrases": list(keyterms)}
    if diarize:
        payload["diarize"] = True
        payload["response_format"] = "verbose_json"
        payload["timestamp_granularities"] = ["segment"]
        azure["diarization"] = {"enabled": True}
    if azure:
        provider["options"] = {"azure": azure}
    if provider:
        payload["provider"] = provider
    return payload


def _without(payload: dict, top_keys=(), azure_keys=()) -> dict:
    p = json.loads(json.dumps(payload))
    for k in top_keys:
        p.pop(k, None)
    azure = p.get("provider", {}).get("options", {}).get("azure", {})
    for k in azure_keys:
        azure.pop(k, None)
    provider = p.get("provider")
    if provider is not None:
        if not provider.get("options", {}).get("azure"):
            provider.get("options", {}).pop("azure", None)
        if not provider.get("options"):
            provider.pop("options", None)
        if not provider:
            p.pop("provider")
    return p


def drop_keyterms_field(payload: dict) -> dict:
    """Keep the vocabulary only in the provider-native form (model rejected OpenRouter `keyterms`)."""
    return _without(payload, top_keys=("keyterms",))


def drop_vocabulary(payload: dict) -> dict:
    return _without(payload, top_keys=("keyterms",), azure_keys=("phraseList",))


def drop_diarization(payload: dict) -> dict:
    """The same request without speaker labels (fallback when the provider rejects them)."""
    p = _without(payload, top_keys=("diarize", "timestamp_granularities"), azure_keys=("diarization",))
    p["response_format"] = "json"
    return p


def rejects_keyterms_field(message: str) -> bool:
    return "keyterms" in (message or "").lower()


# --- Speaker labels (spec 002 FR-015) --------------------------------------------------------------

_SPEAKER_RE = re.compile(r"(?i)^(?:speaker|spk|guest)?[\s_#-]*(\d+)$")


def speaker_name(segment: dict):
    """Normalise a segment's speaker to 'Speaker N' (or the provider's own label). None if absent."""
    for key in ("speaker_label", "speaker"):
        value = segment.get(key)
        if value is None or isinstance(value, bool) or value == "":
            continue
        if isinstance(value, (int, float)):
            return f"Speaker {int(value)}"
        text = " ".join(str(value).split())
        m = _SPEAKER_RE.match(text)
        return f"Speaker {int(m.group(1))}" if m else text[:40]
    return None


def compact_segments(segments):
    """Keep only what rendering needs (for the per-part cache)."""
    out = []
    for s in segments or []:
        if not isinstance(s, dict):
            continue
        text = " ".join(str(s.get("text") or "").split())
        if text:
            start = s.get("start")
            out.append({"start": float(start) if isinstance(start, (int, float)) else None,
                        "speaker": speaker_name(s), "text": text})
    return out


def speaker_turns(segments, offset_seconds: float):
    """Merge consecutive same-speaker segments. Returns [(start_seconds, speaker, text)], or None when the
    model returned no speaker information."""
    if not segments or not any(s.get("speaker") for s in segments):
        return None
    turns = []
    for s in segments:
        speaker = s.get("speaker") or "Speaker ?"
        start = offset_seconds + (s["start"] if s.get("start") is not None else 0.0)
        if turns and turns[-1][1] == speaker:
            turns[-1] = (turns[-1][0], speaker, turns[-1][2] + " " + s["text"])
        else:
            turns.append((start, speaker, s["text"]))
    return turns


def part_body(result: dict, part_index: int) -> str:
    """Text for one part: speaker-labelled turns with recording-relative timestamps when available,
    otherwise the plain text."""
    turns = speaker_turns(result.get("segments"), part_index * PART_SECONDS)
    if not turns:
        return (result.get("text") or "").strip()
    return "\n\n".join(f"[{format_duration(start)}] {speaker}: {text}" for start, speaker, text in turns)


def speakers_status(requested: bool, labelled_flags) -> str | None:
    if not requested:
        return None
    flags = list(labelled_flags)
    if flags and any(flags):
        return (f"labelled per {PART_SECONDS // 60}-minute section; the same person can get a different "
                "number in another section")
    return "not returned by the model"


RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504, 524, 529}


def is_retryable(status) -> bool:
    return status is None or status in RETRYABLE_STATUS


def error_message(status, provider_message: str, model: str) -> str:
    """Plain-language failure reason (spec 002 FR-014). Never includes secrets."""
    detail = " ".join((provider_message or "").split())[:300]
    known = {
        401: "OpenRouter: API key rejected - run scripts/set-openrouter-key.sh",
        402: "OpenRouter: insufficient credits - add credits at openrouter.ai",
        403: "OpenRouter: request not permitted for this key or model",
        404: f"OpenRouter: model '{model}' not found or not available for transcription",
        413: "OpenRouter: audio part too large for the provider",
        429: "OpenRouter: rate limited - try Retry later",
    }
    if status in known:
        base = known[status]
    elif status is None:
        base = "OpenRouter: network error or timeout"
    elif status in (504, 524):
        base = "OpenRouter: the provider timed out"
    elif status and status >= 500:
        base = f"OpenRouter: provider error ({status})"
    else:
        base = f"OpenRouter: request rejected ({status})"
    return f"{base}: {detail}" if detail else base


# --- Transcript rendering --------------------------------------------------------------------------

def vocabulary_status(term_count: int, applied_flags, via_phrase_list: bool = False) -> str:
    flags = list(applied_flags)
    if term_count == 0:
        return "none"
    if all(flags):
        return f"{term_count} terms" + (" (as Azure phrase list)" if via_phrase_list else "")
    if not any(flags):
        return "not applied (rejected by provider)"
    return f"{term_count} terms (not applied to {flags.count(False)} of {len(flags)} parts: rejected by provider)"


def render_transcript(meta: dict, texts, model: str, vocab_status: str, cost=None, speakers=None) -> str:
    local = local_start(meta["startedAt"], meta["tzOffsetMinutes"])
    lines = []
    if meta.get("title"):
        lines.append(f"Title: {meta['title']}")
    if meta.get("sourceName"):
        lines.append(f"Source file: {meta['sourceName']}")
    lines += [
        f"Recorded: {local:%Y-%m-%d %H:%M:%S} ({format_offset(meta['tzOffsetMinutes'])})",
        f"Duration: {format_duration(meta['durationSeconds'])}",
        f"Model: {model}",
        f"Vocabulary: {vocab_status}",
    ]
    if speakers:
        lines.append(f"Speakers: {speakers}")
    if cost is not None:
        lines.append(f"Cost: US${cost:.4f}")
    lines.append(f"Recording ID: {meta['recordingId']}")
    body = "\n\n".join(t.strip() for t in texts if t and t.strip())
    if not body:
        body = "(No speech was detected in this recording.)"
    return "\n".join(lines) + "\n\n" + body + "\n"


# --- Listing ---------------------------------------------------------------------------------------

def validate_month(value) -> str:
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        raise ValidationError("month must be YYYY-MM")
    return value


def validate_transcript_key(value) -> str:
    if not isinstance(value, str) or not _TRANSCRIPT_KEY_RE.match(value):
        raise ValidationError("invalid transcript key")
    return value


def transcript_item(key: str, size: int):
    m = _TRANSCRIPT_KEY_RE.match(key)
    if not m:
        return None
    return {
        "key": key,
        "name": key.rsplit("/", 1)[1],
        "recordedAt": f"{m.group(2)} {m.group(3)}:{m.group(4)}:{m.group(5)}",
        "size": size,
    }


def sort_newest_first(values):
    return sorted(values, reverse=True)
