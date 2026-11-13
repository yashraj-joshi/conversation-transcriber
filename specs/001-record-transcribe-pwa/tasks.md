---
description: "Task list for 001-record-transcribe-pwa"
---

# Tasks: Record & Transcribe Conversations (Mobile & Desktop Web App)

**Input**: Design documents from `/specs/001-record-transcribe-pwa/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required by Constitution VI for backend core logic (offline unit tests).

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [x] T001 Create repo layout `frontend/`, `backend/src`, `backend/tests`, `infra/`, `scripts/` and root `.gitignore`
- [x] T002 [P] Terraform providers/backends in `infra/versions.tf`, inputs in `infra/variables.tf`, locals in `infra/main.tf`
- [x] T003 [P] `infra/terraform.tfvars.example`

## Phase 2: Foundational (blocks all stories)

- [x] T004 Data bucket (private, TLS-only, versioning, SSE, lifecycle for `audio/` + `status/`, CORS POST) in `infra/storage.tf`
- [x] T005 [P] Cognito user pool (admin-only sign-up) + public client in `infra/auth.tf`
- [x] T006 [P] SSM SecureString placeholder for the API key (OpenRouter, per 002) in `infra/lambda.tf`
- [x] T007 Pure core logic (key naming, local-time bucketing, validation, transcript rendering) in `backend/src/core.py`
- [x] T008 Unit tests for core in `backend/tests/test_core.py`
- [x] T009 [P] `scripts/create-user.sh` and `scripts/set-openrouter-key.sh` (002)

**Checkpoint**: Storage, auth, secrets, and core logic exist.

## Phase 3: User Story 1 — Record & get a saved transcript (P1) 🎯 MVP

- [x] T010 [US1] ~~OpenAI multipart client~~ → OpenRouter client in `backend/src/openrouter_client.py` (002 T104)
- [x] T011 [US1] Transcriber handler (manifest → parts → OpenAI → `transcripts/YYYY-MM/…txt` + status, idempotent) in `backend/src/transcriber.py`
- [x] T012 [US1] API handler: `POST /uploads`, `POST /recordings/{id}/complete`, `GET /recordings/{id}` in `backend/src/api.py`
- [x] T013 [P] [US1] Tests in `backend/tests/test_transcriber.py` and `backend/tests/test_api.py`, WAV parts from every browser (002 T107)
- [x] T014 [US1] Lambda functions, IAM (least privilege), S3 → Lambda notification, async retries = 0 in `infra/lambda.tf`
- [x] T015 [US1] HTTP API, JWT authorizer, routes, CORS for the single CloudFront origin in `infra/api.tf`
- [x] T016 [US1] Frontend recorder → Web Audio WAV, 5-min parts, pause/resume, wake lock in `frontend/recorder.js` (002 T108)
- [x] T017 [US1] Cognito sign-in/refresh in `frontend/auth.js`; API client in `frontend/api.js`
- [x] T018 [US1] Record screen, upload pipeline, status polling in `frontend/app.js`, `frontend/index.html`, `frontend/styles.css` (mobile-first layout)

**Checkpoint**: Recording → transcript in S3 works end-to-end (quickstart V2–V4).

## Phase 4: User Story 2 — Install like an app on iPhone (P1)

- [x] T019 [P] [US2] `frontend/manifest.webmanifest` (`display: standalone`, 192/512 px icons), Apple meta tags
- [x] T020 [P] [US2] Icons via `scripts/make_icons.py` → `frontend/icons/`
- [x] T021 [US2] Service worker app-shell cache in `frontend/sw.js`; "Add to Home Screen" hint shown only on iOS/iPadOS Safari when not standalone (never on desktop)
- [x] T022 [US2] Web bucket, CloudFront + OAC + CSP headers, object uploads, generated `config.js` in `infra/frontend.tf`; outputs in `infra/outputs.tf`

**Checkpoint**: Quickstart V1 passes.

## Phase 5: User Story 3 — Use it as a website on a computer (P2)

- [x] T023 [US3] Responsive layout in `frontend/styles.css`: single column < 768 px, centered wide layout ≥ 768 px, no horizontal scroll from 375 px to 1280 px+
- [x] T024 [US3] Mouse/keyboard support in `frontend/app.js` and `frontend/index.html`: real buttons, visible focus styles, `Space` starts/stops recording on the Record screen
- [x] T025 [US3] Desktop microphone-permission hint (browser site permissions; macOS System Settings → Privacy & Security → Microphone) in `frontend/app.js`
- [x] T026 [US3] On `visibilitychange`/`pagehide` while recording (e.g. laptop sleep), close and keep the current part and tell the owner recording stopped, in `frontend/recorder.js`
- [x] T027 [US3] Two-pane Transcripts layout (list + transcript side by side at ≥ 768 px) in `frontend/styles.css` and `frontend/app.js` (after T029)

**Checkpoint**: Quickstart V8–V9 pass.

## Phase 6: User Story 4 — Browse transcripts by month (P2)

- [x] T028 [US4] API: `GET /transcripts/months`, `GET /transcripts?month=`, `GET /transcript?key=` in `backend/src/api.py` (+ tests)
- [x] T029 [US4] Transcripts tab: months → list → viewer with Copy, Share (when `navigator.share` exists) or Download `.txt` otherwise, in `frontend/app.js`

## Phase 7: User Story 5 — Survive interruptions (P3)

- [x] T030 [US5] IndexedDB queue for parts/recordings in `frontend/store.js`
- [x] T031 [US5] Persist each part before upload; resume pending uploads on launch/online; Retry button in `frontend/app.js`

## Phase 8: Polish

- [x] T032 [P] `README.md` with architecture, deploy, costs, supported browsers, limitations
- [x] T033 Run gates: unit tests, `terraform fmt -check`, `terraform validate`

## Dependencies

- Phase 2 blocks all stories. US1 backend (T010–T015) precedes US1 frontend (T016–T018).
- US2 (T022) is needed to serve the frontend from AWS, but the frontend can be tested locally before it.
- US3 depends on US1. T027 (two-pane transcripts) also depends on the US4 viewer (T029).
- US4 and US5 depend only on US1.
