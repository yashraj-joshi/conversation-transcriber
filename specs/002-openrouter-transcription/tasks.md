---
description: "Task list for 002-openrouter-transcription (delivered together with 001)"
---

# Tasks: Transcribe via OpenRouter with a Configurable Model and Custom Vocabulary

**Input**: [spec.md](./spec.md), [plan.md](./plan.md), and the 001 task list (all 001 tasks are delivered in
the same change; 001 T010, T013, T016, and T009's key script are superseded as noted).

## Phase 1: Documents

- [x] T101 Spec, checklist, plan for 002; constitution → 1.1.0; annotate 001 spec/research/data-model/contracts/quickstart
- [x] T102 [P] `config/vocabulary.txt` with the user's list

## Phase 2: Backend (US1, US2, US3)

- [x] T103 Core: vocabulary parsing, OpenRouter request building, error-message mapping, 5-min/60-part limits, WAV-only content types in `backend/src/core.py` (supersedes 001 T007 limits)
- [x] T104 OpenRouter client with retry/backoff in `backend/src/openrouter_client.py` (supersedes 001 T010)
- [x] T105 Transcriber: model from SSM, key from SSM, vocabulary from S3, parallel parts, per-part cache, vocabulary fallback in `backend/src/transcriber.py`
- [x] T106 API handler (001 T012, T028) in `backend/src/api.py`
- [x] T107 [P] Tests: `test_core.py`, `test_openrouter_client.py`, `test_transcriber.py`, `test_api.py` (supersedes 001 T013)

## Phase 3: Frontend (US1)

- [x] T108 WAV capture: `frontend/pcm-worklet.js`, `frontend/wav.js`, `frontend/recorder.js` with 5-min parts, 10-s IndexedDB flush, 5-h cap with warning (supersedes 001 T016)
- [x] T109 [P] `frontend/tests/wav.test.mjs` (`node --test`)
- [x] T110 Remaining 001 frontend tasks (T017–T019, T021, T023–T027, T029–T031)

## Phase 4: Infrastructure (US2, US3)

- [x] T111 SSM parameters `transcription-model` (ignore_changes) and `openrouter-api-key`; IAM scoped to both in `infra/lambda.tf`
- [x] T112 Vocabulary S3 object + `work/` lifecycle in `infra/storage.tf`
- [x] T113 Remaining 001 infra tasks (T002–T006, T014, T015, T022)

## Phase 5: Scripts & docs (US4)

- [x] T114 `scripts/set-openrouter-key.sh`, `scripts/set-model.sh`, `scripts/push-vocabulary.sh`, `scripts/create-user.sh`, `scripts/make_icons.py`
- [x] T115 `README.md` (FR-013); update 001 `quickstart.md` to OpenRouter

## Phase 6: Clarifications 2026-11-13

- [x] T117 3-hour cap: `MAX_PARTS` 36 / `MAX_DURATION_SECONDS` 10800 in `backend/src/core.py`, `MAX_SECONDS` in `frontend/recorder.js`, UI messages, contracts, docs
- [x] T118 [US5] Speaker labels: request building, segment normalisation, turn rendering in `backend/src/core.py`; feature fallback and cache in `backend/src/transcriber.py`; `var.speaker_labels` → `DIARIZE`; tests

## Phase 7: Gates

- [x] T116 (re-run after T117–T118) `python3 -m unittest`, `node --test frontend/tests`, `node --check` on frontend JS, `terraform fmt -check`, `terraform validate`
