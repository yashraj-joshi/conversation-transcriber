<!--
Sync Impact Report
- Version change: 1.0.0 → 1.0.1 (PATCH: wording clarification)
- Modified: Technology & Cost Constraints → "Client" now states a single-URL PWA usable in desktop and
  mobile browsers and installable on iPhone (was iPhone-only wording)
- Principles: unchanged
- Templates requiring updates: none ✅ (feature 001 spec/plan/tasks updated in the same change)
- Deferred TODOs: none
-->

# Conversation Transcriber Constitution

## Core Principles

### I. Spec-Driven Delivery

Every feature starts as a specification in `specs/NNN-feature/spec.md`, followed by `plan.md` and
`tasks.md`, before code is written. The spec describes WHAT and WHY; the plan describes HOW. Code
that contradicts the spec is a defect; if the spec is wrong, the spec is amended first.

### II. Serverless-First

The system MUST run on managed, pay-per-use AWS services (S3, CloudFront, API Gateway, Lambda,
Cognito, SSM). No always-on servers, containers, or databases are introduced unless a spec proves a
serverless option cannot meet a requirement, and the exception is recorded in the plan's Complexity
Tracking table.

### III. Infrastructure as Code

All cloud resources MUST be declared in Terraform under `infra/`. Manual console changes are not
allowed, with one exception: secret *values* (e.g. the OpenAI API key) are written out-of-band so they
never enter Terraform state or source control. `terraform fmt` and `terraform validate` MUST pass.

### IV. Secure & Private by Default (NON-NEGOTIABLE)

Recordings and transcripts are personal data. Buckets MUST be private with public access blocked and
TLS enforced. Every API route MUST require an authenticated user. Self sign-up is disabled. IAM
policies are least-privilege and scoped to specific resources. Secrets live in SSM Parameter Store
(SecureString), never in code, environment files, or Terraform state. Uploads are size-bounded so a
leaked token cannot run up unbounded OpenAI or AWS cost.

### V. Simplicity Over Tooling

Prefer the platform over frameworks: the web app is plain HTML/CSS/JavaScript with no build step;
the backend uses only the Python standard library plus the boto3 bundled in the Lambda runtime.
New dependencies require a written justification in the plan. YAGNI applies.

### VI. Testable Core Logic

Business logic (S3 key naming, date bucketing, manifest validation, transcript assembly, OpenAI
request building) MUST live in pure functions with unit tests runnable via `python3 -m unittest`.
AWS and OpenAI clients are injected so tests run offline with no credentials.

## Technology & Cost Constraints

- Cloud: AWS, single region (configurable, default `us-east-1`).
- Transcription: OpenAI Audio Transcriptions API using the account's platform credits; the model is a
  configuration value, not hard-coded.
- Client: a single-URL Progressive Web App, usable as a website in desktop and mobile browsers and
  installable on iPhone ("Add to Home Screen"). No separate desktop site; no native App Store app.
- Storage layout is a contract: transcripts are grouped into one folder per month, and file names
  begin with the date and time so they sort chronologically.
- Raw audio is transient and expires automatically; transcripts are retained.

## Development Workflow

1. `/speckit-constitution` → `/speckit-specify` → (`/speckit-clarify`) → `/speckit-plan` →
   `/speckit-tasks` → `/speckit-implement`.
2. Tasks are checked off in `tasks.md` as they are completed.
3. Quality gates before deploy: unit tests pass, `terraform fmt -check` and `terraform validate` pass.
4. Deploy with `terraform apply` from `infra/`; never by hand.

## Governance

This constitution supersedes other practices. Amendments are made by editing this file, bumping the
version (MAJOR: principle removed/redefined; MINOR: principle/section added; PATCH: wording), and
updating dependent templates. Every plan MUST include a Constitution Check that passes or justifies
each deviation.

**Version**: 1.0.1 | **Ratified**: 2026-11-11 | **Last Amended**: 2026-11-11
