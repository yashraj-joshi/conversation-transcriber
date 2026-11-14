# Implementation Plan: Transcribe an Uploaded Audio File

**Branch**: `003-upload-audio-file` | **Date**: 2026-11-13 | **Spec**: [spec.md](./spec.md)

## Summary

`frontend/importer.js` reads the chosen file with `OfflineAudioContext(1, 1, 16000).decodeAudioData()`,
which decodes and resamples in one native call. If the browser refuses a 16 kHz context, it falls back to
44.1 kHz plus the existing JS resampler. Input is processed in 10-second slices: mixed to mono
(`wav.mixToMono`), converted to Int16, and encoded into 5-minute WAV parts (`wav.encodeWav`). The parts
are written to IndexedDB through `store.putPart`. The recording record is created first with state
`importing`, then switched to `uploading` with its `partCount`, after which the existing upload pump,
manifest, transcriber, status polling, and Retry take over unchanged. The backend accepts an optional
`sourceName` on `POST /recordings/{id}/complete` and prints `Source file: …` in the transcript header.

## Decisions

- **Decode in the browser (Web Audio)**, not on the server. It needs no ffmpeg layer (Constitution V), and
  it reuses the 002 pipeline. Safari decodes AAC/M4A/MP3/WAV/FLAC; Chrome and Edge also decode Ogg/Opus/WebM.
- **Decode straight to 16 kHz.** Memory is samples × channels × 4 B: 1 h stereo ≈ 460 MB (at 48 kHz it
  would be 1.4 GB). Streaming decode (WebCodecs plus a demuxer) is rejected as too complex. Instead, the
  limits are documented: about 1 h on iPhone and 3 h on desktop.
- **Leftovers are cleaned up.** On launch, records in state `importing` (an interrupted preparation) are
  deleted together with their parts.
- **No change to the API contract beyond `sourceName`.** Limits (36 parts, 18 MB, 3 h) are enforced exactly
  as for recordings.

## Constitution Check

| Principle | Status | Evidence |
|---|---|---|
| I. Spec-Driven | ✅ | spec/plan/tasks in `specs/003-upload-audio-file/` |
| II. Serverless | ✅ | No new services |
| III. IaC | ✅ | Only frontend files and Lambda code change; deployed by `terraform apply` |
| IV. Secure | ✅ | Same presigned POST limits; `sourceName` length-limited and reduced to its base name |
| V. Simplicity | ✅ | No dependencies; Web Audio only |
| VI. Testable | ✅ | `mixToMono`, `partRanges`, `floatToInt16` unit-tested (node); `sourceName` validation/rendering (unittest) |
