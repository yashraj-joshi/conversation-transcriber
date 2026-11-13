# Data Model

No database is used. All entities are S3 objects (see [contracts/storage-layout.md](./contracts/storage-layout.md))
or IndexedDB records on the device.

## Recording (manifest) — `audio/<recordingId>/manifest.json`

| Field | Type | Rules |
|-------|------|-------|
| `recordingId` | string | UUID v4 (client-generated, lowercase) |
| `startedAt` | string | ISO-8601 UTC, e.g. `2026-11-11T22:30:05.120Z`; not > 10 min in future |
| `tzOffsetMinutes` | int | −840 … 840 (minutes east of UTC) |
| `durationSeconds` | number | 1 … 10800 (3 h; amended by 002) |
| `partCount` | int | 1 … 36 (`MAX_PARTS`, 3 h at 5 min/part; amended by 002) |
| `parts` | array | `[{ "index": 0, "key": "audio/<id>/part-000.wav", "contentType": "audio/wav" }]` |
| `title` | string? | ≤ 120 chars, optional |
| `submittedBy` | string | Cognito `sub` (set by server) |
| `submittedAt` | string | ISO-8601 UTC (set by server) |

## Audio Part — `audio/<recordingId>/part-NNN.<ext>`

- `NNN` is the zero-padded index (000–035). `ext` is one of `wav`, `mp3`, `flac` (the browser always writes
  16 kHz mono `wav`; amended by 002).
- Size is 1 B – 18 MB (enforced by the presigned POST policy; 18 MB raw stays under OpenRouter's 25 MB
  base64 limit).
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
Model: microsoft/mai-transcribe-2
Vocabulary: 313 terms
Speakers: labelled per 5-minute section; the same person can get a different number in another section
Cost: US$0.0700           (when the provider reports it)
Recording ID: 3f2c…

[00:00:01] Speaker 1: <turn text>

[00:00:14] Speaker 2: <turn text>   (plain text per part when no speaker labels)
```

## Part Result (002) — `work/<recordingId>/part-NNN.json`

`{ index, model, text, segments: [{start, speaker, text}], speakersLabelled, diarizeRequested, cost, seconds, vocabularyApplied }`, written after each part is transcribed and
reused on Retry when `model` matches. Expires with `audio/`.

```text
```

S3 object metadata includes `recording-id`, `started-at`, and `duration-seconds`.

## Device: Pending Recording (IndexedDB `conversation-transcriber`)

- Store `recordings`: `{ id, startedAt, tzOffsetMinutes, durationSeconds, title, partCount|null, state }`.
  `state` is one of `recording`, `uploading`, `submitted`, `done`, `failed`.
- Store `parts` (key `[recordingId, index]`): `{ recordingId, index, data: ArrayBuffer (WAV), contentType, samples }`.
  The part is deleted after it uploads.
- Store `chunks` (key `[recordingId, partIndex, seq]`): 10-second Int16 PCM blocks of the part being recorded
  (002 FR-012). They are combined into a part and deleted in one transaction.
- `recordings` also tracks `closedParts` and `closedSamples` so a crashed recording can be finalised.
