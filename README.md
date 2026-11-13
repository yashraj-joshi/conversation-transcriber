# Conversation Transcriber

Record a conversation on your iPhone (installed to the home screen) or in a desktop browser. Each recording
is transcribed through [OpenRouter](https://openrouter.ai) by a speech-to-text model you choose (default
**MAI-Transcribe 2**, `microsoft/mai-transcribe-2`). The model is helped by a custom vocabulary of your own
terms (and can optionally label who is speaking), and the transcript is saved to S3 as a text file in a folder per month:

```text
transcripts/2026-11/2026-11-11_14-30-05_3f2c9a1b.txt
```

Everything runs serverless on AWS and is deployed with Terraform. Specs: [001 record & transcribe](specs/001-record-transcribe-pwa/spec.md),
[002 OpenRouter, model & vocabulary](specs/002-openrouter-transcription/spec.md).

## How it works

```text
 iPhone / desktop browser (one URL)
   │  microphone → AudioWorklet → 16 kHz mono WAV, saved to IndexedDB every 10 s
   │  every 5 min of audio → one WAV part (~9.6 MB), uploaded in the background while recording
   │
   ├─ sign in ───────────────────────────▶ Cognito (admin-created users only)
   ├─ POST /uploads (JWT) ───────────────▶ API Gateway ─▶ api Lambda ─▶ presigned POST (≤ 18 MB, audio/wav)
   ├─ POST part ─────────────────────────▶ S3  audio/<id>/part-000.wav, part-001.wav, …
   ├─ POST /recordings/{id}/complete ────▶ api Lambda ─▶ audio/<id>/manifest.json
   │                                               │ S3 event
   │                                               ▼
   │                       transcriber Lambda ── reads model  ◀─ SSM /<project>/transcription-model
   │                                          ── reads key    ◀─ SSM /<project>/openrouter-api-key (SecureString)
   │                                          ── reads terms  ◀─ S3  config/vocabulary.txt
   │                                          ── 4 parts at a time ─▶ OpenRouter /api/v1/audio/transcriptions
   │                                          ── writes transcripts/YYYY-MM/…txt + status/<id>.json
   └─ GET status / months / transcripts ─▶ api Lambda
 CloudFront (HTTPS, CSP) ─▶ private S3 bucket with the static PWA (no build step)
```

Why WAV and 5-minute parts? MAI-Transcribe 2 only accepts WAV, MP3 or FLAC, and browsers' built-in
recorders produce mp4/webm. OpenRouter takes audio as base64 JSON with a 25 MB per-request limit. A
5-minute 16 kHz WAV is 9.6 MB, or 12.8 MB once base64-encoded. Details:
[specs/002-openrouter-transcription/plan.md](specs/002-openrouter-transcription/plan.md).

## Repository layout

```text
backend/src/        core.py (pure logic) · openrouter_client.py · api.py · transcriber.py
backend/tests/      unittest suites with in-memory S3/SSM/HTTP fakes (offline, no AWS SDK needed)
config/             vocabulary.txt — the custom vocabulary (one term per line)
frontend/           static PWA: index.html, app.js, recorder.js, pcm-worklet.js, wav.js, store.js, auth.js, api.js, sw.js
frontend/tests/     node --test suite for the WAV encoder / resampler
infra/              Terraform (S3, CloudFront, Cognito, API Gateway, Lambda, SSM)
scripts/            set-openrouter-key.sh · set-model.sh · push-vocabulary.sh · create-user.sh · make_icons.py
specs/              Spec Kit specs, plans, tasks
```

## Prerequisites

- An AWS account and the AWS CLI v2, configured: `aws sts get-caller-identity` works. You need
  permissions to create S3, CloudFront, Cognito, API Gateway, Lambda, IAM, SSM and CloudWatch Logs
  resources.
- Terraform ≥ 1.6
- Python ≥ 3.11 (tests and helper scripts)
- Node.js ≥ 20 (only for the frontend unit tests)
- An OpenRouter account with credits and an API key (<https://openrouter.ai/keys>)

## 1. Run the tests

```bash
python3 -m unittest discover -s backend/tests -t backend/tests
node --test frontend/tests/wav.test.mjs
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false && terraform -chdir=infra validate
```

## 2. Deploy

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars   # optional: region, project name, model, …
terraform -chdir=infra init
terraform -chdir=infra apply                              # ~5 min (CloudFront takes the longest)

./scripts/set-openrouter-key.sh                           # paste your sk-or-… key (stored as SSM SecureString)
./scripts/create-user.sh you@example.com                  # sets a permanent password (min 12 chars)

terraform -chdir=infra output app_url                     # open this URL on the phone and the computer
```

Terraform state is local (`infra/terraform.tfstate`, git-ignored). The OpenRouter key never enters
the state: Terraform creates a `REPLACE_ME` placeholder and ignores later changes to it.

### Install on iPhone

Open `app_url` in Safari, tap **Share → Add to Home Screen**, then launch it from the icon. Keep the app in
the foreground with the screen on while recording. iOS stops web-app recording in the background. The app
keeps the screen awake and saves what was captured if it is interrupted.

On a Mac or PC, use the same URL in Chrome, Edge or Safari. Chrome and Edge also offer **Install app**.

## 3. Change the transcription model

The model id is the SSM String parameter `/<project>/transcription-model`. A change applies to the **next
recording**, with no redeploy, and `terraform apply` will not overwrite it.

```bash
./scripts/set-model.sh                              # show the current model + OpenRouter STT models
./scripts/set-model.sh microsoft/mai-transcribe-2   # set it
```

Pick a model that accepts WAV audio (most speech-to-text models do). If a model rejects the request,
the recording shows Failed with the provider's message, and Retry works after you switch back. Each
transcript's header records the model that produced it.

## 4. Edit the custom vocabulary

`config/vocabulary.txt` holds one term per line. Blank lines and lines starting with `#` are ignored,
duplicates are removed, and terms longer than 100 characters are skipped. Up to 1000 terms are sent with
every request as OpenRouter `keyterms`. The terms are hints that bias spelling; the model is not forced to
use them.

```bash
$EDITOR config/vocabulary.txt
terraform -chdir=infra apply            # or, quicker: ./scripts/push-vocabulary.sh
```

If the provider rejects the vocabulary (e.g. too many terms for that model), the part is transcribed again
without it. The transcript header then says `Vocabulary: not applied (rejected by provider)`. Microsoft
recommends at most ~200 phrases for its phrase lists. If you see that message, shorten the list to your
most important terms.

## 5. Speaker labels

Off by default. To turn them on, set `speaker_labels = true` in `infra/terraform.tfvars` and run
`terraform -chdir=infra apply`. Transcripts then look like this:

```text
Speakers: labelled per 5-minute section; the same person can get a different number in another section

[00:00:02] Speaker 1: Shall we start with the deployment?

[00:00:06] Speaker 2: Yes, the Lambda cold start is the issue.
```

The model labels each 5-minute part on its own, so numbers can change between sections; the timestamps
keep the timeline continuous. If a model doesn't support speaker labels, the part is transcribed as plain
text.

## 6. Local frontend development

```bash
# 1. allow the local origin, then apply:   extra_allowed_origins = ["http://localhost:8000"]  in terraform.tfvars
# 2. create frontend/config.js from the outputs:
cp frontend/config.example.js frontend/config.js      # fill region, user_pool_client_id, api_url
python3 -m http.server -d frontend 8000              # open http://localhost:8000 (mic works on localhost)
```

`frontend/config.js` is git-ignored; Terraform generates the deployed one.

## Configuration reference

| Setting | Where | Default |
|---|---|---|
| Transcription model | SSM `/<project>/transcription-model` (`scripts/set-model.sh`) | `microsoft/mai-transcribe-2` |
| OpenRouter API key | SSM SecureString `/<project>/openrouter-api-key` (`scripts/set-openrouter-key.sh`) | placeholder |
| Custom vocabulary | `config/vocabulary.txt` → `s3://<data-bucket>/config/vocabulary.txt` | 313 terms |
| Privacy routing | `openrouter_data_collection` (tfvars) | `deny` (only providers that don't store/train on audio) |
| Speaker labels | `speaker_labels` (tfvars) | `false` |
| Parallel requests | `transcribe_parallelism` | 4 |
| Raw audio retention | `audio_retention_days` | 30 days (transcripts are kept) |
| Region / name | `region`, `project` | `us-east-1`, `conversation-transcriber` |

## Costs (approximate, November 2026)

- **Idle:** under US$1/month. CloudFront, Lambda, API Gateway and Cognito stay within the free tiers at
  personal scale; S3 costs cents.
- **Transcription:** MAI-Transcribe 2 on OpenRouter costs about **US$0.10 per hour of audio**. The transcript
  header shows the cost reported by OpenRouter.
- **Storage:** WAV is about 115 MB per hour. Raw audio is deleted after 30 days, so a heavy month is about
  1–2 GB, roughly US$0.03.
- **Mobile data:** about 115 MB per hour of recording. Uploads run in the background during recording.

## Limits

- Recording length: up to **3 hours**. You get a warning 5 minutes before, then it stops and is transcribed
  automatically. Recordings shorter than 1 second are discarded.
- Each part is 5 minutes and at most 18 MB. A recording has at most 36 parts.
- A crash or closed tab loses at most the last ~10 seconds. The rest is recovered and uploaded the next
  time the app opens.
- Speaker numbers are per 5-minute section, so the same person can be "Speaker 1" in one section and
  "Speaker 2" in the next. Timestamps run across the whole recording.
- Supported browsers: iPhone Safari on iOS 17+, plus current desktop Chrome, Edge and Safari 17+. Firefox
  is best-effort.

## Security

- Buckets are private, with TLS enforced and public access blocked. The site is only reachable through
  CloudFront, which sends a strict CSP and a `Permissions-Policy` that allows only the microphone.
- Every API route requires a Cognito JWT. Self sign-up is disabled, and users are created with
  `scripts/create-user.sh`.
- The OpenRouter key lives only in SSM SecureString. It is not in code, Terraform state or Lambda
  environment variables.
- Uploads are bounded: 18 MB per part, `audio/wav|mpeg|flac` only, 36 parts, 3 hours, and the API is
  throttled at 10 req/s. A leaked token therefore cannot run up unbounded cost.
- A failed transcription is never retried automatically by AWS (async retries = 0). Retry is your choice,
  and parts already transcribed are not billed again.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Failed: OpenRouter: API key rejected` | `./scripts/set-openrouter-key.sh`, then **Retry** in the app |
| `Failed: OpenRouter: insufficient credits` | Add credits at openrouter.ai, then **Retry** |
| `Failed: model '…' not found` | `./scripts/set-model.sh` to list valid models; set one; **Retry** |
| `Failed: OpenRouter: request rejected (404/400) … no endpoints` with privacy routing | Set `openrouter_data_collection = "allow"` and apply |
| Stays "Uploading" | Check connectivity. Uploads resume automatically when online or when the app is reopened |
| Microphone blocked | iPhone: Settings → Apps → Safari → Microphone. Mac: site settings in the address bar, plus System Settings → Privacy & Security → Microphone |

Logs:

```bash
aws logs tail /aws/lambda/conversation-transcriber-transcriber --follow
aws logs tail /aws/lambda/conversation-transcriber-api --follow
aws s3 ls s3://$(terraform -chdir=infra output -raw data_bucket)/transcripts/ --recursive
```

## Tear down

The data bucket holds your transcripts, and the user pool is deletion-protected. Both are deliberate.

```bash
B=$(terraform -chdir=infra output -raw data_bucket)
aws s3 cp s3://$B/transcripts ./transcripts-backup --recursive          # keep a copy
aws s3api delete-objects --bucket "$B" --delete "$(aws s3api list-object-versions --bucket "$B" \
  --query '{Objects: [Versions, DeleteMarkers][][].{Key: Key, VersionId: VersionId}}' --output json)"  # repeat while objects remain (≤1000 per call)
terraform -chdir=infra apply -var protect_user_pool=false        # lift Cognito deletion protection
terraform -chdir=infra destroy -var protect_user_pool=false
```
