# Data Model

No database is used. All entities are S3 objects (see [contracts/storage-layout.md](./contracts/storage-layout.md))
or IndexedDB records on the device.

## Recording (manifest) — `audio/<recordingId>/manifest.json`

| Field | Type | Rules |
|-------|------|-------|
| `recordingId` | string | UUID v4 (client-generated, lowercase) |
| `startedAt` | string | ISO-8601 UTC, e.g. `2026-11-11T22:30:05.120Z`; not > 10 min in future |
| `tzOffsetMinutes` | int | −840 … 840 (minutes east of UTC) |
| `durationSeconds` | number | 1 … 18000 (5 h) |
| `partCount` | int | 1 … 30 (`MAX_PARTS`, 5 h at 10 min/part) |
| `parts` | array | `[{ "index": 0, "key": "audio/<id>/part-000.mp4", "contentType": "audio/mp4" }]` |
| `title` | string? | ≤ 120 chars, optional |
| `submittedBy` | string | Cognito `sub` (set by server) |
| `submittedAt` | string | ISO-8601 UTC (set by server) |

## Audio Part — `audio/<recordingId>/part-NNN.<ext>`

- `NNN` is the zero-padded index (000–029). `ext` is one of `mp4`, `m4a`, `webm`, `ogg`, `wav`, `mp3`.
- Size is 1 B – 25 MB (enforced by the presigned POST policy).
- Expires after `audio_retention_days` (default 30).

## Status — `status/<recordingId>.json`

| Field | Type | Notes |
|-------|------|-------|
| `recordingId` | string | |
| `state` | enum | `transcribing` → `done` \| `failed` |
| `transcriptKey` | string? | set when `done` |
| `error` | string? | set when `failed` (no secrets) |
| `updatedAt` | string | ISO-8601 UTC |

State transitions: (none) → `transcribing` → `done`, or `transcribing` → `failed` → (retry) →
`transcribing`. A manifest arriving while `done` is a no-op.

## Transcript — `transcripts/<YYYY-MM>/<YYYY-MM-DD>_<HH-MM-SS>_<id8>.txt`

UTF-8 plain text:

```text
Title: Weekly sync            (only if provided)
Recorded: 2026-11-11 14:30:05 (UTC-08:00)
Duration: 00:42:17
Model: gpt-transcribe
Recording ID: 3f2c…

<full transcript text; parts joined by a blank line>
```

S3 object metadata includes `recording-id`, `started-at`, and `duration-seconds`.

## Device: Pending Recording (IndexedDB `conversation-transcriber`)

- Store `recordings`: `{ id, startedAt, tzOffsetMinutes, durationSeconds, title, partCount|null, state }`.
  `state` is one of `recording`, `uploading`, `submitted`, `done`, `failed`.
- Store `parts`: `{ key: "<id>:<index>", recordingId, index, blob, contentType, uploaded:boolean }`.
  The part is deleted after it uploads.
