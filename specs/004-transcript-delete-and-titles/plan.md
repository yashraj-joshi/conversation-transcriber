# Implementation Plan: Delete & Restore Transcripts; AI Titles and Summaries

**Spec**: [spec.md](./spec.md) | **Date**: 2026-11-14

## Decisions

### D1. Soft delete = move to `trash/`

`POST /transcripts/delete {key}` copies `transcripts/YYYY-MM/<name>.txt` to
`trash/transcripts/YYYY-MM/<name>.txt` (metadata copied), deletes the original, then deletes
`audio/<recordingId>/*` and `work/<recordingId>/*` (the id comes from the object's `recording-id`
metadata). A lifecycle rule expires `trash/` 90 days after the copy, which is the deletion time.
`GET /transcripts/deleted` lists `trash/` with `deletedAt` (LastModified) and `purgeAt` (+90 days).
`POST /transcripts/restore {key}` copies it back. It returns 409 if the original key exists, and otherwise
deletes the trash copy. `GET /transcript?key=` accepts `trash/…` keys.

- **Rejected**: S3 version-based undelete. Delete markers are hard to list as a "Deleted" folder, and
  restore would need version ids. An explicit prefix is simpler and visible in the console.

### D2. Titles and summaries in the transcript header

After assembly, the transcriber calls OpenRouter `POST /api/v1/chat/completions` with the model from SSM
`/<project>/summary-model` (default `anthropic/claude-haiku-5.5`, `ignore_changes`). It uses
`response_format: json_schema` `{title, summary}` (verified live on 2026-11-14: 369 input + 140 output
tokens cost US$0.0001), `temperature 0.2`, `max_tokens 400`, and `provider.data_collection` as for
transcription. The input is the transcript body, capped at 600,000 characters (well inside the 1M-token
context). The result is written into the header as `AI title:` and `Summary:` lines, placed directly after
`Title:`. Its cost is added to `Cost:`. On any failure, it logs a warning and saves the transcript without
the lines.

- **Listing**: `GET /transcripts?month=` reads the first 4 KB of each transcript (a ranged GET, 8 in
  parallel) and parses the header, so no extra index objects can drift out of sync on delete or restore.
  - **Rejected**: S3 object metadata. ListObjects doesn't return it, and non-ASCII values need RFC 2047
    encoding.
  - **Rejected**: a month index file. It risks lost updates when transcriptions run concurrently.

### D3. Backfill

The transcriber accepts a direct invocation `{"action": "retitle", "month": "YYYY-MM", "force": false}`. It
adds the lines to transcripts that lack them (or to all of them, with `force`). Run it with
`scripts/retitle.sh YYYY-MM`.

### D4. UI

- **Transcripts tab:** month chips plus a **Deleted** chip.
- **List items:** title, then date · time, then the summary (clamped to 2 lines).
- **Viewer:** Copy, Share/Download, plus **Delete**, which confirms via `confirm()`. For trash items it
  shows **Restore** and a banner with the purge date.
- **Device list:** "Remove" becomes **Hide**. After a delete, the local entry for that recording id is
  hidden.
- **Uploads:** the title is no longer prefilled with the file name.

## Constitution Check

| Principle | Status | Evidence |
|---|---|---|
| I Spec-Driven | ✅ | `specs/004-…` spec/plan/tasks |
| II Serverless | ✅ | No new services; one SSM parameter, one lifecycle rule, 3 routes |
| III IaC | ✅ | All in Terraform |
| IV Secure | ✅ | Keys validated by regex (only `transcripts/` and `trash/transcripts/`); IAM scoped by prefix; summary uses `data_collection: deny`; JWT on new routes |
| V Simplicity | ✅ | stdlib only; no index store |
| VI Testable | ✅ | header parse/set, summary request/parse, trash key mapping in `core.py` with unit tests; API and transcriber tested with fakes |
