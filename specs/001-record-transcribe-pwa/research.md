# Phase 0 Research: Record & Transcribe Conversations

> **Amended 2026-11-13 by [002](../002-openrouter-transcription/plan.md):** R1 (model), R2 (10-min parts + prompt chaining), R3 (MediaRecorder mp4/webm) and R8 (OpenAI key) are
> superseded: the transcriber calls OpenRouter with the model read from SSM, and the browser records
> 16 kHz mono WAV in 5-minute parts. R4–R7 and R9–R11 still apply.


## R1. Transcription model

- **Decision**: Default `gpt-transcribe`, configurable via Terraform variable `openai_model`.
- **Rationale**: The OpenAI speech-to-text guide (checked 2026-11-11) lists `gpt-transcribe` as the
  recommended model. `whisper-1`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` and
  `gpt-4o-transcribe-diarize` are deprecated and shut down on 2027-02-26. `gpt-transcribe` returns JSON
  with `text` and `languages` and accepts `prompt`.
- **Alternatives**: `gpt-4o-transcribe-diarize` would give speaker labels, but it is deprecated, so it is
  out of scope for v1 (see the spec's Assumptions).

## R2. Long recordings vs. the 25 MB file limit

- **Decision**: The client rotates `MediaRecorder` every 10 minutes of active recording. Each part is a
  standalone, decodable file of about 5 MB at 64 kbps. The worker transcribes parts sequentially and passes
  the tail (≈ 400 chars) of the previous part's text as `prompt`, which keeps context across a cut.
- **Rationale**: This avoids server-side audio splitting (ffmpeg layers, extra deps) and keeps each request
  far below 25 MB. Parts already uploaded survive an app crash. OpenAI recommends against cutting
  mid-sentence; passing the prompt reduces the accuracy loss at boundaries.
- **Alternatives**: Using `timeslice` chunks is rejected because only the first chunk carries container
  headers. Server-side ffmpeg splitting is rejected because it needs a binary layer. Realtime API
  streaming is rejected as more complex, and it holds a connection open for the whole conversation.

## R3. Recording format (iOS and desktop)

- **Decision**: Prefer `audio/mp4` (AAC). Fall back to `audio/webm;codecs=opus`, then the browser
  default. Set `audioBitsPerSecond: 64000`. Upload with extension `.mp4`/`.webm` to match the format,
  because OpenAI detects format from the file name.
- **Rationale**: Safari's MediaRecorder (iOS and macOS) produces `audio/mp4`. Desktop Chrome and Edge
  produce webm. OpenAI accepts both, so desktop recording needs no server-side change.

## R4. Keeping a recording alive (iOS and desktop)

- **Decision**: Request a Screen Wake Lock while recording and show a "keep the app open" notice.
- **Rationale**: iOS suspends web apps in the background, and there is no web API to keep recording.
  This is documented as a platform limitation. Wake Lock is also supported in desktop Chrome, Edge, and
  Safari, where it stops the display from sleeping during a long recording. It cannot stop a laptop
  lid-close sleep, so the recorder closes the current part on `visibilitychange`/`pagehide` and keeps it.

## R5. Upload path

- **Decision**: The API returns an S3 **presigned POST** for each part, with conditions for an exact key,
  `Content-Type` starting with `audio/`, and `content-length-range` 1 B – 25 MB. The browser posts
  straight to S3. The presigned POST expires after 15 minutes.
- **Rationale**: This bypasses the API Gateway (10 MB) and Lambda (6 MB) payload limits, and it enforces the
  size limit on the server side, unlike presigned PUT.

## R6. Async processing trigger

- **Decision**: An S3 `ObjectCreated` notification on prefix `audio/` and suffix `manifest.json` invokes the
  transcriber. Async retries are set to 0, so a failure does not bill OpenAI twice. The worker is
  idempotent: it skips work when `status/<id>.json` already says `done`. The user can retry, which
  re-writes the manifest.
- **Alternatives**: SQS/Step Functions are rejected as unnecessary at this scale.

## R7. Authentication

- **Decision**: A Cognito User Pool with admin-only user creation and an app client without a secret,
  using `ALLOW_USER_PASSWORD_AUTH` and `ALLOW_REFRESH_TOKEN_AUTH`. The browser calls the Cognito
  `InitiateAuth` JSON API directly, with no SDK. A HTTP API JWT authorizer validates the **ID token**
  (`aud` = client id).
- **Rationale**: It needs no hosted UI redirect dance inside a standalone PWA, has no SDK dependency,
  and costs nothing at this scale.
- **Trade-off**: The refresh token is kept in `localStorage`. This is acceptable for a personal app
  served under a strict CSP.

## R8. Secret management

- **Decision**: Terraform creates the SSM SecureString `/<project>/openai-api-key` with a placeholder and
  `ignore_changes = [value]`. `scripts/set-openai-key.sh` writes the real value. The Lambda reads it
  once per cold start.
- **Rationale**: The key never appears in state, code, or Lambda environment variables.

## R9. Naming & time zone

- **Decision**: The client sends `startedAt` (UTC ISO-8601) and `tzOffsetMinutes`, which is the inverse of
  JS `getTimezoneOffset()` (minutes east of UTC). The server computes local time, the folder is
  `YYYY-MM`, and the file name is `YYYY-MM-DD_HH-MM-SS_<first 8 chars of id>.txt`.
- **Rationale**: Lexicographic order equals chronological order inside a month. The id suffix guarantees
  uniqueness.

## R10. Static hosting & caching

- **Decision**: A private S3 bucket fronted by CloudFront with OAC. Files are uploaded by Terraform
  (`aws_s3_object`, `etag = filemd5`) with `Cache-Control: no-cache`, so updates appear on the next load
  without invalidations. The service worker uses network-first for the app shell. There is a custom
  response-headers policy with CSP.

## R11. One URL for phone and desktop

- **Decision**: Serve one responsive PWA from the single CloudFront URL to every device. Use CSS media
  queries (single column below 768 px; two-pane month/transcript layout at 768 px and wider) and
  feature detection, never user-agent sniffing:
  - Share button only when `navigator.share` exists. Otherwise (e.g. desktop Chrome on macOS) show Copy
    (`navigator.clipboard.writeText`) and Download (a `Blob` + `<a download>` `.txt` file).
  - The "Add to Home Screen" hint only on iOS/iPadOS Safari when not running standalone
    (`navigator.standalone !== true` and not `display-mode: standalone`).
  - Pointer and keyboard support: real `<button>` elements, visible focus styles, and `Space` to
    start/stop recording on the Record screen.
- **Rationale**: A PWA is a website, so one deployment covers both cases. Cognito sign-in uses
  `USER_PASSWORD_AUTH` (R7), so there are no per-origin callback URLs, and the API's CORS already allows
  that one origin. The manifest's `display: standalone` also enables "Install app" in desktop Chrome/Edge
  and "Add to Dock" in macOS Safari, at no extra cost.
- **Alternatives**: A separate desktop site or subdomain is rejected: two deployments and two CORS
  origins with no user benefit. Device detection with redirects is rejected as fragile and contrary to
  the "same URL" requirement (FR-001).
