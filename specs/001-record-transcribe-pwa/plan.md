# Implementation Plan: Record & Transcribe Conversations (Mobile & Desktop Web App)

**Branch**: `001-record-transcribe-pwa` | **Date**: 2026-11-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-record-transcribe-pwa/spec.md`

## Summary

> **Amended 2026-11-13 by [002](../002-openrouter-transcription/plan.md):** transcription now goes through OpenRouter (model in SSM, custom vocabulary), and recording
> uses Web Audio → 16 kHz WAV in 5-minute parts. `openai_client.py` became `openrouter_client.py`;
> `set-openai-key.sh` became `set-openrouter-key.sh`. Where this plan disagrees with 002, 002 wins.


An installable PWA records audio in the browser with `MediaRecorder`, splitting long conversations into
10-minute parts. Each part is persisted to IndexedDB and uploaded straight to a private S3 bucket using
a short-lived presigned POST from an authenticated API. When the recording is finished, the app posts a
manifest; the S3 event invokes a transcriber Lambda that sends each part, in order, to the OpenAI
transcription API (`gpt-transcribe`), joins the text, and writes one `.txt` file to
`transcripts/YYYY-MM/YYYY-MM-DD_HH-MM-SS_<id>.txt`. Static hosting is S3 + CloudFront; auth is a
Cognito user pool with an API Gateway HTTP API JWT authorizer; the OpenAI key is in SSM. Everything is
Terraform.

The same CloudFront URL serves every device. One responsive layout covers iPhone (installed to the
home screen or in Safari) and desktop Chrome/Safari/Edge: a single column below 768 px, and two panes
(list + transcript) at 768 px and wider. There is no separate desktop site, user-agent sniffing, or
redirect (research R11).

## Technical Context

**Language/Version**: Python 3.13 (Lambda), vanilla ES2022 JavaScript (browser), HCL (Terraform ≥ 1.6)

**Primary Dependencies**: boto3 (bundled in Lambda runtime), Python stdlib (`urllib`, `json`); no npm
packages; Terraform providers `hashicorp/aws ~> 6.0`, `hashicorp/archive ~> 2.4`

**Storage**: Amazon S3 (audio parts, manifests, status records, transcripts); IndexedDB on device
(pending audio)

**Testing**: `python3 -m unittest` (offline, injected fakes); `terraform validate`

**Target Platform**: iOS 17+ Safari / home-screen web app (primary); current desktop Chrome, Edge, and
Safari 17+ on macOS (full support); Firefox best-effort; all at one URL. Backend on AWS Lambda.

**Project Type**: Web application (static PWA + serverless API + async worker)

**Performance Goals**: 10-minute recording transcribed in < 3 min (SC-001)

**Constraints**: OpenAI 25 MB/file limit; API Gateway 30 s sync limit (so transcription is async);
Lambda 15 min max runtime (≈ 4–5 h of audio at ~20–30 s per 10-min part); idle cost < US$1/month

**Scale/Scope**: 1 owner + a few invited users; tens of recordings per month

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Spec-Driven Delivery | ✅ | spec → plan → tasks precede code in `specs/001-record-transcribe-pwa/` |
| II. Serverless-First | ✅ | S3, CloudFront, HTTP API, Lambda, Cognito, SSM only; no servers or DB |
| III. Infrastructure as Code | ✅ | All resources in `infra/*.tf`; only the OpenAI key value is set via CLI |
| IV. Secure & Private | ✅ | Private buckets + OAC, TLS-only policies, JWT on all routes, admin-only sign-up, SSM SecureString, presigned POST with `content-length-range`, part-count cap |
| V. Simplicity | ✅ | No frontend build, no backend packages; a single Lambda zip serves both functions |
| VI. Testable Core | ✅ | `backend/src/core.py` holds pure logic; handlers take injected clients |

*Post-design re-check (after Phase 1)*: ✅ still passing; no Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-record-transcribe-pwa/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── api.openapi.yaml # HTTP API contract
│   └── storage-layout.md# S3 key contract
├── checklists/requirements.md
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
frontend/                       # Static PWA (no build step), uploaded to S3 by Terraform
├── index.html
├── styles.css                  # Responsive: 1 column < 768 px, two-pane Transcripts ≥ 768 px
├── app.js                      # UI, routing, views; Share → Copy/Download fallback; iOS-only install hint
├── auth.js                     # Cognito USER_PASSWORD_AUTH + refresh
├── api.js                      # Authenticated API client
├── recorder.js                 # MediaRecorder with part rotation, pause/resume, wake lock
├── store.js                    # IndexedDB queue of pending parts/recordings
├── sw.js                       # Service worker (app-shell cache)
├── manifest.webmanifest        # standalone display: iPhone home screen + Chrome/Edge desktop install
├── config.example.js           # config.js is generated by Terraform
└── icons/                      # apple-touch-icon + PWA icons

backend/
├── src/
│   ├── core.py                 # Pure logic: keys, dates, validation, transcript assembly
│   ├── openai_client.py        # Multipart request to /v1/audio/transcriptions with retries
│   ├── api.py                  # HTTP API Lambda handler (routes)
│   └── transcriber.py          # S3-event Lambda handler
└── tests/
    ├── test_core.py
    ├── test_api.py
    └── test_transcriber.py

infra/                          # Terraform
├── versions.tf  variables.tf  main.tf  outputs.tf
├── storage.tf                  # data + web buckets, lifecycle, CORS, policies
├── auth.tf                     # Cognito user pool + client
├── lambda.tf                   # IAM, functions, S3 notification, SSM parameter
├── api.tf                      # HTTP API, JWT authorizer, routes
├── frontend.tf                 # CloudFront + OAC + file uploads + config.js
└── terraform.tfvars.example

scripts/
├── create-user.sh              # Admin creates the owner account
├── set-openai-key.sh           # Writes the OpenAI key to SSM (never to state)
└── make_icons.py               # Generates PNG icons (stdlib only)
```

**Structure Decision**: Web application layout with `frontend/`, `backend/`, and `infra/` at the repo
root. The PWA is served as static files, so there is no frontend build pipeline.

## Architecture

```text
 Browser / PWA ──(1) sign in───────────▶ Cognito User Pool
 (iPhone or desktop, same URL)
     │
     ├──(2) POST /uploads (JWT) ───────▶ HTTP API ─▶ api Lambda ─▶ presigned POST
     ├──(3) POST part ─────────────────▶ S3 data bucket  audio/<id>/part-000.mp4
     ├──(4) POST /recordings/{id}/complete ─▶ api Lambda ─▶ audio/<id>/manifest.json
     │                                                          │ S3 ObjectCreated
     │                                                          ▼
     │                                        transcriber Lambda ──▶ OpenAI /v1/audio/transcriptions
     │                                                          │
     │                                    transcripts/2026-11/2026-11-11_14-30-05_<id>.txt
     │                                    status/<id>.json
     ├──(5) GET /recordings/{id} (poll status)
     └──(6) GET /transcripts/months · /transcripts?month= · /transcript?key=
 CloudFront (OAC) ─▶ S3 web bucket (index.html, app.js, config.js, …)
```

## Complexity Tracking

No constitution violations.
