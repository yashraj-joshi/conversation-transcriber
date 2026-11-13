# Quickstart & Validation Guide

> The full operator guide (deploy, model, vocabulary, local dev, costs, teardown) is the repository
> [README](../../README.md). This page keeps the validation scenarios.

## Prerequisites

- AWS CLI v2 configured for the target account (`aws sts get-caller-identity` works)
- Terraform ≥ 1.6, Python 3.11+, Node.js 20+ (frontend unit tests only)
- An OpenRouter API key with credits

## 1. Local gates

```bash
python3 -m unittest discover -s backend/tests -t backend/tests   # backend tests pass
node --test frontend/tests/wav.test.mjs                             # WAV encoder/resampler tests pass
terraform -chdir=infra fmt -check && terraform -chdir=infra init -backend=false && terraform -chdir=infra validate
```

## 2. Deploy

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars    # edit region/project if desired
terraform -chdir=infra init
terraform -chdir=infra apply
./scripts/set-openrouter-key.sh                              # prompts for the key; stores it in SSM
./scripts/create-user.sh you@example.com                     # prompts for a password
terraform -chdir=infra output app_url
```

## 3. Validation scenarios

| # | Scenario | Expected |
|---|----------|----------|
| V1 (US2) | Open `app_url` in iPhone Safari → Share → Add to Home Screen → launch | Full-screen app with its icon and name |
| V2 (US1) | Sign in, Record ~60 s of speech, Stop | Status goes Uploading → Transcribing → Done; text is shown |
| V3 (US1) | `aws s3 ls s3://$(terraform -chdir=infra output -raw data_bucket)/transcripts/ --recursive` | `transcripts/YYYY-MM/YYYY-MM-DD_HH-MM-SS_xxxxxxxx.txt` for the current local month |
| V4 (US1) | Record > 5 min | At least 2 `part-NNN.wav` under `audio/<id>/` (uploaded while still recording); one transcript containing all the speech |
| V10 (002 US2) | `./scripts/set-model.sh <other-model>`, record 30 s | Transcript header `Model:` shows the new model; no redeploy |
| V11 (002 US3) | Read a script of 30 vocabulary terms | Header shows `Vocabulary: N terms`; ≥ 27 terms spelled as in `config/vocabulary.txt` |
| V5 (US4) | Transcripts tab → month → item | Months newest first; items newest first; Copy/Share work |
| V6 (US5) | Airplane mode → record → stop → network on → reopen app | Pending recording uploads and is transcribed |
| V7 (Sec) | `curl $(terraform -chdir=infra output -raw api_url)/transcripts/months` without a token | HTTP 401 |
| V8 (US3) | Open the **same** `app_url` in Chrome and in Safari on a Mac → sign in → record ~60 s with the built-in mic → Stop | Transcript lands in the same `transcripts/YYYY-MM/` folder as iPhone recordings; it appears in the Transcripts view on both devices |
| V9 (US3) | On desktop Chrome, open a transcript; then resize the window from full width down to ~375 px | Wide: list and text side by side, Copy + Download (no Share). Narrow: single column, no horizontal scroll. No "Add to Home Screen" hint on desktop |

## 4. Troubleshooting

- Worker logs: `aws logs tail /aws/lambda/<project>-transcriber --follow`
- API logs: `aws logs tail /aws/lambda/<project>-api --follow`
