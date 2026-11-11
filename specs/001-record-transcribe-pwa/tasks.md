---
description: "Task list for 001-record-transcribe-pwa"
---

# Tasks: Record & Transcribe Conversations (Mobile & Desktop Web App)

**Input**: Design documents from `/specs/001-record-transcribe-pwa/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required by Constitution VI for backend core logic (offline unit tests).

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [ ] T001 Create repo layout `frontend/`, `backend/src`, `backend/tests`, `infra/`, `scripts/` and root `.gitignore`
- [ ] T002 [P] Terraform providers/backends in `infra/versions.tf`, inputs in `infra/variables.tf`, locals in `infra/main.tf`
- [ ] T003 [P] `infra/terraform.tfvars.example`

## Phase 2: Foundational (blocks all stories)

- [ ] T004 Data bucket (private, TLS-only, versioning, SSE, lifecycle for `audio/` + `status/`, CORS POST) in `infra/storage.tf`
- [ ] T005 [P] Cognito user pool (admin-only sign-up) + public client in `infra/auth.tf`
- [ ] T006 [P] SSM SecureString placeholder for the OpenAI key in `infra/lambda.tf`
- [ ] T007 Pure core logic (key naming, local-time bucketing, validation, transcript rendering) in `backend/src/core.py`
- [ ] T008 Unit tests for core in `backend/tests/test_core.py`
- [ ] T009 [P] `scripts/create-user.sh` and `scripts/set-openai-key.sh`

**Checkpoint**: Storage, auth, secrets, and core logic exist.

## Phase 3: User Story 1 — Record & get a saved transcript (P1) 🎯 MVP

- [ ] T010 [US1] OpenAI multipart client with retry/backoff in `backend/src/openai_client.py`
- [ ] T011 [US1] Transcriber handler (manifest → parts → OpenAI → `transcripts/YYYY-MM/…txt` + status, idempotent) in `backend/src/transcriber.py`
- [ ] T012 [US1] API handler: `POST /uploads`, `POST /recordings/{id}/complete`, `GET /recordings/{id}` in `backend/src/api.py`
- [ ] T013 [P] [US1] Tests in `backend/tests/test_transcriber.py` and `backend/tests/test_api.py`, including `.mp4` (Safari) and `.webm` (Chrome) parts
- [ ] T014 [US1] Lambda functions, IAM (least privilege), S3 → Lambda notification, async retries = 0 in `infra/lambda.tf`
- [ ] T015 [US1] HTTP API, JWT authorizer, routes, CORS for the single CloudFront origin in `infra/api.tf`
- [ ] T016 [US1] Frontend recorder with 10-min part rotation, pause/resume, wake lock, `audio/mp4` → `audio/webm` fallback in `frontend/recorder.js`
- [ ] T017 [US1] Cognito sign-in/refresh in `frontend/auth.js`; API client in `frontend/api.js`
- [ ] T018 [US1] Record screen, upload pipeline, status polling in `frontend/app.js`, `frontend/index.html`, `frontend/styles.css` (mobile-first layout)

**Checkpoint**: Recording → transcript in S3 works end-to-end (quickstart V2–V4).

## Phase 4: User Story 2 — Install like an app on iPhone (P1)

- [ ] T019 [P] [US2] `frontend/manifest.webmanifest` (`display: standalone`, 192/512 px icons), Apple meta tags
- [ ] T020 [P] [US2] Icons via `scripts/make_icons.py` → `frontend/icons/`
- [ ] T021 [US2] Service worker app-shell cache in `frontend/sw.js`; "Add to Home Screen" hint shown only on iOS/iPadOS Safari when not standalone (never on desktop)
- [ ] T022 [US2] Web bucket, CloudFront + OAC + CSP headers, object uploads, generated `config.js` in `infra/frontend.tf`; outputs in `infra/outputs.tf`

**Checkpoint**: Quickstart V1 passes.

## Phase 5: User Story 3 — Use it as a website on a computer (P2)

- [ ] T023 [US3] Responsive layout in `frontend/styles.css`: single column < 768 px, centered wide layout ≥ 768 px, no horizontal scroll from 375 px to 1280 px+
- [ ] T024 [US3] Mouse/keyboard support in `frontend/app.js` and `frontend/index.html`: real buttons, visible focus styles, `Space` starts/stops recording on the Record screen
- [ ] T025 [US3] Desktop microphone-permission hint (browser site permissions; macOS System Settings → Privacy & Security → Microphone) in `frontend/app.js`
- [ ] T026 [US3] On `visibilitychange`/`pagehide` while recording (e.g. laptop sleep), close and keep the current part and tell the owner recording stopped, in `frontend/recorder.js`
- [ ] T027 [US3] Two-pane Transcripts layout (list + transcript side by side at ≥ 768 px) in `frontend/styles.css` and `frontend/app.js` (after T029)

**Checkpoint**: Quickstart V8–V9 pass.

## Phase 6: User Story 4 — Browse transcripts by month (P2)

- [ ] T028 [US4] API: `GET /transcripts/months`, `GET /transcripts?month=`, `GET /transcript?key=` in `backend/src/api.py` (+ tests)
- [ ] T029 [US4] Transcripts tab: months → list → viewer with Copy, Share (when `navigator.share` exists) or Download `.txt` otherwise, in `frontend/app.js`

## Phase 7: User Story 5 — Survive interruptions (P3)

- [ ] T030 [US5] IndexedDB queue for parts/recordings in `frontend/store.js`
- [ ] T031 [US5] Persist each part before upload; resume pending uploads on launch/online; Retry button in `frontend/app.js`

## Phase 8: Polish

- [ ] T032 [P] `README.md` with architecture, deploy, costs, supported browsers, limitations
- [ ] T033 Run gates: unit tests, `terraform fmt -check`, `terraform validate`

## Dependencies

- Phase 2 blocks all stories. US1 backend (T010–T015) precedes US1 frontend (T016–T018).
- US2 (T022) is needed to serve the frontend from AWS, but the frontend can be tested locally before it.
- US3 depends on US1. T027 (two-pane transcripts) also depends on the US4 viewer (T029).
- US4 and US5 depend only on US1.
