# Implementation Plan: Transcribe via OpenRouter with a Configurable Model and Custom Vocabulary

**Branch**: `002-openrouter-transcription` | **Date**: 2026-11-13 | **Spec**: [spec.md](./spec.md)

**Builds on**: [001 plan](../001-record-transcribe-pwa/plan.md). 001 was not implemented before this
change, so both features are delivered together. Where this plan and 001 disagree, this plan wins. The
001 documents carry notes pointing here.

## Summary

The transcriber Lambda calls OpenRouter's `POST https://openrouter.ai/api/v1/audio/transcriptions` with a
JSON body (`model`, base64 `input_audio`, `keyterms`, `provider`). The model id is read from SSM String
parameter `/<project>/transcription-model` (initial value `microsoft/mai-transcribe-2`; Terraform ignores
later changes to it). The key is read from SSM SecureString `/<project>/openrouter-api-key`. The vocabulary is
`config/vocabulary.txt` in the repo, uploaded by Terraform to `s3://<data-bucket>/config/vocabulary.txt`
and sent as OpenRouter `keyterms`. Because MAI-Transcribe 2 only accepts WAV/MP3/FLAC, the browser now
records 16 kHz mono PCM through an AudioWorklet and writes WAV parts of 5 minutes (9.6 MB, so 12.8 MB after
base64 encoding, under the 25 MB inline limit). Parts are transcribed in parallel (4 at a time). The text
of each part is cached under `work/<id>/` so Retry never re-bills it.

## Research (Phase 0)

### R1. OpenRouter speech-to-text endpoint

- **Decision**: JSON body `{ model, input_audio: { data: <base64>, format: "wav" }, keyterms: [...],
  provider: { data_collection: "deny" } }` → response `{ text, usage: { seconds, cost } }`.
  Auth: `Authorization: Bearer <key>`.
- **Sources** (checked 2026-11-13): OpenRouter STT guide and API reference `create-transcription`. Errors:
  400 invalid, 401 key, 402 credits, 403 permission, 404 not found, 413 too large, 429 rate limit, 5xx/524/529
  upstream. The upstream provider deadline is 60 s per request.
- **Alternatives**: Multipart upload (OpenAI-compatible) is limited to 25 MB, and some docs say its
  `prompt` is ignored. JSON is the documented primary path. `input_audio.url` (provider downloads a
  presigned S3 URL) would remove base64, but it is not documented for the Azure provider, so it is not used.

### R2. Model input format → WAV capture in the browser

- **Decision**: Capture with Web Audio (`getUserMedia` → `AudioWorkletNode`). The worklet averages input
  samples down to 16 kHz mono and posts Int16 frames. The page writes a 44-byte RIFF header.
- **Rationale**: The Microsoft MAI-Transcribe docs list only WAV, MP3, and FLAC. Safari's MediaRecorder
  produces AAC/mp4 and Chrome's produces Opus/webm, so neither is accepted. Server-side conversion would
  need ffmpeg (a binary layer), and MP3/FLAC encoding in the browser would need a third-party library.
  Both conflict with Constitution V. 16 kHz mono PCM is the native rate of speech models.
- **Cost**: 32 KB/s ≈ 115 MB per hour of upload, compared with ≈ 29 MB at 64 kbps AAC. This is acceptable for
  a personal tool, uploads run in the background during recording, and it is documented in the README.

### R3. Part length and request size

- **Decision**: 5-minute parts (4.8 M samples, 9.6 MB WAV, 12.8 MB base64). The presigned POST caps parts
  at 18 MB. `MAX_PARTS` = 36 (3 h, per the 2026-11-13 clarification).
- **Rationale**: A 10-minute WAV becomes 25.6 MB after base64 encoding, which is over the 25 MB inline cap.
  5 minutes also stays well inside the 60 s upstream deadline.

### R4. Custom vocabulary

- **Decision**: Send OpenRouter's top-level `keyterms` (max 1000 items, 1–100 chars each). If a request
  that carried keyterms gets a 400, retry that part once without them and mark the transcript
  "Vocabulary: not applied (rejected by provider)".
- **Rationale**: `keyterms` is OpenRouter's provider-neutral field, so it keeps working if the model changes.
  Azure's own equivalent is `phraseList.phrases`, which MAI-Transcribe 2 supports. Microsoft documents a hard
  cap of 200 phrases / 3,200 characters for one recognition mode and advises ≤ 200 phrases elsewhere. The
  delivered list has 313 terms / 2,757 characters, so the fallback protects against a rejection.
  Hard-coding `provider.options.azure.phraseList` is rejected because it ties the code to one provider.
- **Storage**: A repo file (`config/vocabulary.txt`) is copied to S3 by Terraform. It is not an SSM
  parameter, because the Standard tier allows 4 KB, the list is already 2.7 KB, and it is easier to review
  in diffs.

### R5. Model setting

- **Decision**: An SSM String parameter, created by Terraform from `var.transcription_model` with
  `lifecycle { ignore_changes = [value] }`. `scripts/set-model.sh <model>` changes it. The Lambda reads it
  once per transcription job (one GetParameter call per recording).
- **Rationale**: Satisfies FR-002: a change takes effect without a redeploy, and the next `terraform apply`
  does not overwrite it.

### R6. Throughput and idempotency

- **Decision**: Use a `ThreadPoolExecutor` with `TRANSCRIBE_PARALLELISM` workers (default 4). Write
  `work/<id>/part-NNN.json` (`text`, `cost`, `vocabularyApplied`) after each part. On retry, cached parts are
  reused. `work/` expires with `audio/`.
- **Rationale**: Parts no longer share a prompt (the JSON API has no `prompt`), so they are independent. A
  3-hour recording is 36 parts. Sequentially at about 15 s each that is about 9 min; with 4 workers it is
  about 2–3 min.

### R7. Retries and errors

- **Decision**: Retry 429, 500, 502, 503, 504, 524, 529 and network errors with delays of 2 s, 4 s, 8 s
  (at most 4 attempts, `Retry-After` honoured up to 20 s). Map 401/402/403/404/413 to plain messages
  without retrying.

### R8. Privacy routing

- **Decision**: `provider.data_collection = var.openrouter_data_collection` (default `"deny"`).
  If OpenRouter reports that no provider matches, the owner can set it to `"allow"` and apply.

### R10. Speaker labels (spec FR-015)

- **Decision**: Send `diarize: true`, `response_format: "verbose_json"`, and
  `timestamp_granularities: ["segment"]`, plus `provider.options.azure.diarization.enabled` (the form
  OpenRouter's MAI example uses; options for providers that don't serve the request are not forwarded).
  Normalise `speaker_label`/`speaker` to `Speaker N`. Merge consecutive same-speaker segments. Prefix each turn
  with `[HH:MM:SS]` = `part_index × 300 s + segment.start`. On a 400, drop the vocabulary first, then
  diarization. Per-part results cache `segments`, and the cache is keyed on model + whether diarization was
  requested. Toggle with `var.speaker_labels` (`DIARIZE` env), default `false` (owner, 2026-11-13).
- **Rejected**: Cross-part speaker matching (needs voice embeddings or an extra LLM pass; complexity and cost).

### R9. Crash resilience (spec FR-012)

- **Decision**: While recording, PCM is written to IndexedDB as 10-second chunks. When a part fills up, its
  chunks are combined into a WAV part and deleted in a single transaction. On launch, a recording left in
  state `recording` is finalised from its saved chunks and parts, then uploaded.

## Technical Context

Unchanged from 001, except:

**Primary Dependencies**: none new. Uses Python stdlib (`urllib`, `base64`, `concurrent.futures`), boto3
from the Lambda runtime, and Web Audio / AudioWorklet in the browser.

**Constraints**: 25 MB per OpenRouter request (base64 inline). 60 s upstream deadline per request.
1000 keyterms. Lambda 15 min.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Spec-Driven | ✅ | spec/plan/tasks in `specs/002-openrouter-transcription/`; 001 docs annotated |
| II. Serverless | ✅ | No new services; one extra SSM parameter and one S3 object |
| III. IaC | ✅ | Model parameter and vocabulary object in Terraform; secret values set out-of-band |
| IV. Secure & Private | ✅ | Key in SSM SecureString; `data_collection: deny`; part size capped at 18 MB; IAM scoped to the two parameters, `config/vocabulary.txt`, and `work/*` |
| V. Simplicity | ✅ | No new packages; WAV encoded by hand (about 30 lines) |
| VI. Testable Core | ✅ | Vocabulary parsing, request building, error mapping, and WAV/resample logic are pure and unit-tested |

Constitution amended to 1.1.0 (the transcription constraint now names OpenRouter).

## Project Structure (changes vs 001)

```text
config/vocabulary.txt                    # NEW: custom vocabulary, one term per line
backend/src/openrouter_client.py         # REPLACES openai_client.py
frontend/recorder.js                     # Web Audio WAV capture (replaces MediaRecorder design)
frontend/pcm-worklet.js                  # NEW: AudioWorklet, resample to 16 kHz Int16
frontend/wav.js                          # NEW: pure WAV encoder + resampler (unit-tested with node --test)
frontend/tests/wav.test.mjs              # NEW
infra/lambda.tf                          # + /<project>/transcription-model, /<project>/openrouter-api-key
infra/storage.tf                         # + config/vocabulary.txt object, work/ lifecycle
scripts/set-openrouter-key.sh            # REPLACES set-openai-key.sh
scripts/set-model.sh                     # NEW
scripts/push-vocabulary.sh               # NEW: copies config/vocabulary.txt to S3 without a full apply
README.md                                # NEW
```

## Storage layout additions

```text
config/vocabulary.txt                    # written by Terraform; read by the transcriber
work/<recordingId>/part-NNN.json         # per-part result cache; expires with audio/
audio/<recordingId>/part-NNN.wav         # parts are now WAV
```
