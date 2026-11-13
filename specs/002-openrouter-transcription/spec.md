# Feature Specification: Transcribe via OpenRouter with a Configurable Model and Custom Vocabulary

**Feature Branch**: `002-openrouter-transcription`

**Created**: 2026-11-13

**Status**: Draft

**Amends**: [001-record-transcribe-pwa](../001-record-transcribe-pwa/spec.md). This feature replaces 001
FR-006 (OpenAI as the transcription service). Everything else in 001 still applies.

**Input**: User description: "Instead of using the OpenAI URL, use OpenRouter, with a model name that can
be changed and is stored in SSM Parameter Store. For now use the model MAI-Transcribe 2
(`microsoft/mai-transcribe-2`). Also add a custom vocabulary list that is sent to the model, stored
separately [list of ~310 technical, cloud, AI, finance and household terms]. Build the project, run the
tests, and create a README with deploy instructions."

## Clarifications

### Session 2026-11-13

- Q: What should happen when a recording reaches the maximum length? → A: The maximum is 3 hours (lowered
  from 5). The owner is warned 5 minutes before, then the recording stops automatically and is transcribed.
- Q: Should transcripts include speaker labels even though each 5-minute part is labelled on its own? →
  A: Yes. Each turn is labelled ("Speaker 1: …") with a timestamp from the start of the recording. Speaker
  numbers are assigned per 5-minute section and may differ between sections; the header says so.
- Q: Should speaker labels be on by default? → A: No, off for now; the owner turns them on with a
  deployment setting.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Transcripts come from the chosen model through OpenRouter (Priority: P1)

The owner records a conversation exactly as before (001 User Story 1). Behind the scenes, the recording is
transcribed by the model the owner has configured (initially MAI-Transcribe 2), reached through the
owner's OpenRouter account and paid for with OpenRouter credits. The owner does not need an OpenAI account.

**Why this priority**: Without a working transcription service, the product does nothing.

**Independent Test**: With an OpenRouter key stored and the model set to `microsoft/mai-transcribe-2`,
record 1 minute on an iPhone and 1 minute in desktop Chrome. Both transcripts appear in the month folder,
their headers name `microsoft/mai-transcribe-2`, and the OpenRouter activity page shows two requests for
that model.

**Acceptance Scenarios**:

1. **Given** a stored OpenRouter key and the default model, **When** a recording finishes uploading,
   **Then** it is transcribed by `microsoft/mai-transcribe-2` and the transcript header names that model.
2. **Given** a recording made in iPhone Safari and one made in desktop Chrome, **When** both are
   transcribed, **Then** both succeed. The model accepts the audio format of every supported browser.
3. **Given** a 2-hour recording, **When** it is transcribed, **Then** no request to the transcription
   service exceeds the service's per-request size limit, and one transcript covers the whole conversation
   in spoken order.
4. **Given** the OpenRouter account has no credits or the key is invalid, **When** transcription runs,
   **Then** the recording is marked Failed with a plain message ("OpenRouter: insufficient credits" or
   "OpenRouter: API key rejected"), and Retry works after the owner fixes it.

---

### User Story 2 - Change the model without touching code (Priority: P1)

The owner wants to try a different speech-to-text model (for example a newer or cheaper one). They change
one stored setting, and the next recording uses the new model. No code change and no redeploy are needed.

**Why this priority**: Speech models change quickly and get deprecated, and the user asked for this
explicitly.

**Independent Test**: Change the stored model name to another transcription model available on
OpenRouter, record 30 seconds, and confirm the new transcript's header names the new model.

**Acceptance Scenarios**:

1. **Given** the stored model setting is changed, **When** the next recording is transcribed, **Then** the
   new model is used, without a redeploy.
2. **Given** a later infrastructure deploy, **When** it runs, **Then** it does not overwrite a model
   setting the owner changed by hand.
3. **Given** the stored model name is not a valid OpenRouter model, **When** transcription runs, **Then**
   the recording is marked Failed with a message naming the model, and no audio is lost.

---

### User Story 3 - Technical terms are spelled correctly (Priority: P2)

The owner's conversations are full of technical and domain terms (FastAPI, pgvector, SAA-C03, Powerwall,
401(k)…). A custom vocabulary list, kept as its own file outside the code, is sent with every
transcription request so the model favours these spellings. The owner can add or remove terms by editing
that file and deploying.

**Why this priority**: Better accuracy on the owner's own words, but transcripts are useful without it.

**Independent Test**: Read a script that contains 30 terms from the list (for example "We deployed the
FastAPI service on Fargate behind API Gateway, with pgvector in Aurora") and check how many appear spelled
exactly as in the vocabulary.

**Acceptance Scenarios**:

1. **Given** the vocabulary file contains terms, **When** any recording is transcribed, **Then** the terms
   are sent with every request, and the transcript header shows how many terms were applied.
2. **Given** the owner adds a term to the vocabulary file and deploys, **When** the next recording is
   transcribed, **Then** the new term is included, with no code change.
3. **Given** the vocabulary file has blank lines, comment lines, duplicate terms, or a term longer than
   100 characters, **When** it is loaded, **Then** blanks and comments are ignored, duplicates are sent
   once, and over-long terms are skipped and logged.
4. **Given** the model or provider rejects the vocabulary, **When** transcription runs, **Then** that part
   is transcribed again without the vocabulary, the transcript is still produced, and its header says
   "Vocabulary: not applied (rejected by provider)".
5. **Given** the vocabulary file is empty or missing, **When** transcription runs, **Then** it proceeds
   without a vocabulary.

---

### User Story 5 - See who said what (Priority: P2)

The owner opens a transcript and sees the conversation as speaker turns, each with a time from the start
of the recording: `[00:12:04] Speaker 2: …`. Within each 5-minute section the speakers are told apart. The
same person may get a different number in the next section, but the timestamps and the context make the
conversation readable.

**Why this priority**: Conversations are much easier to follow with turns, but plain text is still useful.

**Independent Test**: Record a 7-minute two-person conversation. The transcript shows alternating speaker
labels with increasing timestamps, and turns after 00:05:00 continue the timeline.

**Acceptance Scenarios**:

1. **Given** speaker labels are enabled (off by default; a deployment setting), **When** a two-person recording is transcribed,
   **Then** each turn starts with `[HH:MM:SS] Speaker N:`, and consecutive sentences by the same speaker are
   merged into one turn.
2. **Given** a recording longer than 5 minutes, **When** it is transcribed, **Then** timestamps run from
   the recording start across sections, and the header says that numbers are per 5-minute section.
3. **Given** the model or provider rejects or ignores speaker labels, **When** transcription runs, **Then**
   the transcript is still produced as plain text, and the header says "Speakers: not returned by the
   model".
4. **Given** the owner turns speaker labels off, **When** a recording is transcribed, **Then** the
   transcript is plain text with no Speakers line.

---

### User Story 4 - Deploy from written instructions (Priority: P2)

Someone with an AWS account and an OpenRouter account follows the README from a fresh clone and ends with
a working app: deploy, store the key, create a user, open the URL. The same document explains how to change
the model, edit the vocabulary, run the tests, and remove everything.

**Why this priority**: The project is only useful if it can be deployed again later, by the owner or
someone else.

**Independent Test**: A person who has not seen the project deploys it from the README alone and records
a first transcript.

**Acceptance Scenarios**:

1. **Given** a fresh clone, **When** the reader follows the README, **Then** every command needed to test,
   deploy, configure the key and model, create a user, and tear down is written out.
2. **Given** the README, **When** the reader looks for costs, limits, and supported browsers, **Then**
   they are stated.

---

### Edge Cases

- Model temporarily overloaded, rate-limited, or timing out → the request is retried automatically with
  increasing delays (at most 4 attempts per part), then the recording is marked Failed with Retry.
- Retry after a partial failure → parts that were already transcribed are not sent again (no double
  charge). Only the failed parts are retried.
- Model changed while a recording is being transcribed → the whole recording uses the model read when its
  transcription started. The header names that model.
- Vocabulary has more than 1000 usable terms → the first 1000 are sent and the rest are logged as skipped.
- The app or browser crashes during a recording → at most the last 10 seconds of audio are lost. Everything
  saved before that is uploaded and transcribed the next time the app opens.
- Recording reaches the 3-hour maximum → the owner is warned 5 minutes before. At 3 hours the recording
  stops automatically and is transcribed as normal.
- Speaker labels and vocabulary both rejected → the vocabulary is dropped first, then the speaker labels.
  The transcript is still produced.
- Uploading on a cellular connection → recordings in the model-compatible format use about 115 MB per
  hour. Upload continues in the background during recording (001 FR-005), so after Stop only the last
  part remains.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST transcribe recordings through OpenRouter's speech-to-text service using the
  owner's OpenRouter credits (replaces 001 FR-006).
- **FR-002**: The model identifier MUST be a stored setting in the cloud configuration store (AWS SSM
  Parameter Store), with the initial value `microsoft/mai-transcribe-2`. A change MUST apply to the next
  transcription without a code change or redeploy, and later deploys MUST NOT overwrite it.
- **FR-003**: The OpenRouter API key MUST be stored as an encrypted secret that is never in source code,
  infrastructure state, or function environment variables.
- **FR-004**: A custom vocabulary list MUST be kept in its own plain-text file, separate from the code (one
  term per line), deployed to cloud storage, and read at transcription time.
- **FR-005**: The vocabulary MUST be sent with every transcription request. When loading it, blank lines
  and lines starting with `#` are ignored, duplicates are removed (first spelling wins), terms longer than
  100 characters are skipped, and at most 1000 terms are sent. Skipped terms are logged.
- **FR-006**: If the provider rejects a request because of the vocabulary, the system MUST retry that part
  once without the vocabulary and record in the transcript header that the vocabulary was not applied. A
  transcript MUST never be lost because of the vocabulary.
- **FR-007**: Audio MUST reach the model in a format it accepts. For MAI-Transcribe 2 that is WAV, MP3, or
  FLAC. Recordings from every supported browser MUST therefore be captured as WAV (16 kHz, mono).
- **FR-008**: Every transcription request MUST stay within the provider's per-request size limit (25 MB).
  Recordings are split into parts of at most 5 minutes of audio (about 10 MB each), and a recording has at
  most 36 parts (3 hours).
- **FR-009**: Each transcript header MUST include the model used and the vocabulary status (number of terms
  applied, or "not applied" with the reason).
- **FR-010**: Parts already transcribed MUST NOT be sent to the service again on Retry.
- **FR-011**: Requests MUST ask OpenRouter to route only to providers that do not collect or train on the
  audio. This is a stored deployment setting that the owner can relax.
- **FR-012**: Audio being recorded MUST be saved on the device at least every 10 seconds, so a crash loses
  at most the last 10 seconds.
- **FR-013**: The repository MUST include a README covering architecture, prerequisites, test, deploy,
  configuration (key, model, vocabulary), user creation, local development, costs, limits, supported
  browsers, troubleshooting, and teardown.
- **FR-015**: When speaker labels are enabled (a deployment setting, off by default since 2026-11-13), the transcript MUST
  show speaker turns as `[HH:MM:SS] Speaker N: text`. Timestamps are relative to the recording start, and
  consecutive segments by the same speaker are merged. The header MUST state that numbering is per 5-minute
  section. If the provider rejects the labels, the part is transcribed again without them (FR-006
  applies).
- **FR-014**: The status of a failed recording MUST show a plain-language reason from the transcription
  service (credits, key, model not found, rate limit, timeout), with no secrets.

### Key Entities

- **Model Setting**: the identifier of the speech-to-text model used for new transcriptions (e.g.
  `microsoft/mai-transcribe-2`). One value per deployment.
- **Vocabulary**: an ordered list of up to 1000 unique terms, each 1–100 characters, shared by all users of
  the deployment. Edited as a text file.
- **Part Result**: the text of one transcribed audio part, plus cost and whether the vocabulary was
  applied. Kept until the audio expires so Retry does not re-bill.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the owner changes the model setting, the very next recording is transcribed by the new
  model. No redeploy is needed.
- **SC-002**: In a scripted test of 30 vocabulary terms read clearly, at least 27 (90%) appear in the
  transcript spelled exactly as in the vocabulary.
- **SC-003**: 0 transcripts are lost because a vocabulary or model setting was rejected. Each such
  recording ends Done or Failed with a clear reason and a working Retry.
- **SC-004**: A person new to the project goes from a fresh clone to a first transcript in under 30 minutes
  using only the README.
- **SC-005**: A 10-minute recording is still transcribed in under 3 minutes after Stop (keeps 001 SC-001).
- **SC-006**: A crash during recording loses at most 10 seconds of audio.

## Assumptions

- The owner has an OpenRouter account with credits. MAI-Transcribe 2 is served on OpenRouter by Azure,
  priced at about US$0.10 per audio hour (November 2026).
- Speaker labels come from the model per 5-minute part. Matching the same voice across parts would need
  voice fingerprints or a second AI pass; this is out of scope (owner accepted per-section numbering on
  2026-11-13). The short parts also keep each request within Azure's shorter limit for diarized audio.
- The vocabulary is one list for the whole deployment, not per user. Terms are hints that favour a
  spelling; the model is not forced to output them.
- WAV audio is larger than the browser's native compressed formats (about 115 MB per hour instead of about
  30 MB). This is accepted so that the model can read every browser's recordings without server-side
  conversion.
- Transcript language is still auto-detected.
- The maximum recording length is 3 hours (see Clarifications). This still meets 001 FR-004 ("at least
  2 hours").
