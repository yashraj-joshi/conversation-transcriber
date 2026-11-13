# Feature Specification: Record & Transcribe Conversations (Mobile & Desktop Web App)

**Feature Branch**: `001-record-transcribe-pwa`

**Created**: 2026-11-11

**Status**: Draft (revised 2026-11-11: desktop browsers added as a first-class target; 2026-11-13:
transcription provider amended by [002](../002-openrouter-transcription/spec.md))

**Input**: User description: "Create a website with an option to open on an iPhone like an app (not an
actual Apple app). Record a conversation using the mobile application; in the backend, using OpenAI API
credits, transcribe it with an OpenAI API call and save the transcription in an S3 bucket, organized by
month, with the files sorted by date inside each folder. Serverless on AWS, deployed with Terraform."
Revision: "It should also open as a regular website on a computer (Mac / Chrome browser), at the same
URL as on the phone."

## Clarifications

### Session 2026-11-13

- Q: Should each 10-minute audio part upload as soon as it is finished while the recording is still
  going, or should all parts wait and upload together after Stop? → A: Upload each part in the
  background as soon as it is finished; after Stop, upload only the last part and then start
  transcription.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record a conversation and get a saved transcript (Priority: P1)

The owner opens the app (from their iPhone home screen or in a browser on their computer), signs in
once, taps or clicks **Record**, has a conversation, and taps **Stop**. Long recordings are uploaded in
parts in the background while recording continues; after Stop only the last part remains to upload. The
recording is then transcribed in the background, and the transcript is saved in that month's folder with a
date-and-time file name. The app shows the progress (uploading → transcribing → done) and then the
transcript text.

**Why this priority**: This is the whole point of the product. Without it, nothing else matters.

**Independent Test**: Record a 1-minute conversation on an iPhone, stop, and confirm that a transcript
file appears in the current month's folder in storage within a few minutes and that its text matches
what was said.

**Acceptance Scenarios**:

1. **Given** the signed-in owner is on the Record screen, **When** they tap Record and allow microphone
   access, **Then** recording starts and an elapsed-time counter is visible.
2. **Given** a recording is in progress, **When** the owner taps Pause and later Resume, **Then** the
   paused interval is not included in the audio and the timer pauses too.
3. **Given** a recording is in progress, **When** the owner taps Stop, **Then** the audio is uploaded and
   the app shows a status that progresses to "Transcribed" without further action.
4. **Given** a recording made on 11 Nov 2026 at 14:30:05 local time, **When** transcription completes,
   **Then** a transcript file is stored in the folder for 2026-11 and its name starts with
   `2026-11-11_14-30-05`.
5. **Given** a conversation longer than 30 minutes, **When** it is stopped, **Then** the full
   conversation is transcribed into a single transcript file, in spoken order.
6. **Given** a recording has been running for more than 10 minutes with a working connection, **When**
   the owner checks storage before tapping Stop, **Then** every finished part is already uploaded, and
   after Stop only the final part is uploaded before transcription starts.

---

### User Story 2 - Install and use it like an app on iPhone (Priority: P1)

The owner visits the website in Safari, uses **Share → Add to Home Screen**, and from then on launches
it from an icon. It opens full-screen without browser bars, has its own icon and name, and the app
shell opens even with poor connectivity.

**Why this priority**: The user explicitly wants an app-like experience on iPhone without a native app.

**Independent Test**: Add the site to the home screen on an iPhone, launch it from the icon, and verify
it opens full-screen with the app's icon/name and no Safari address bar.

**Acceptance Scenarios**:

1. **Given** the site is open in iPhone Safari, **When** the owner adds it to the home screen, **Then** a
   named app icon appears and launching it opens a full-screen experience.
2. **Given** the app is opened in iPhone or iPad Safari, **When** it is not yet installed, **Then** it
   shows a short hint on how to add it to the home screen. The hint is never shown on a desktop
   computer.

---

### User Story 3 - Use it as a website on a computer (Priority: P2)

The owner opens the **same web address** in Chrome, Safari, or Edge on their Mac (or another computer).
The full app works there: signing in, recording from the computer's microphone, and browsing
transcripts. The layout uses the wider screen instead of showing a stretched phone screen. Recordings
made on the computer go into the same transcript archive as recordings made on the phone.

**Why this priority**: The phone is the primary recording device. Reading, copying, and occasionally
recording at a desk is a strong convenience, and it needs no extra infrastructure because it is the same
site.

**Independent Test**: On a Mac, open the app's web address in Chrome, sign in, record a 1-minute
conversation with the built-in microphone, and confirm that the transcript appears in the current
month's folder and in the Transcripts view next to transcripts recorded on the iPhone.

**Acceptance Scenarios**:

1. **Given** the app's web address, **When** it is opened in a current desktop Chrome, Safari, or Edge,
   **Then** the full app loads at that same address, laid out for a wide screen.
2. **Given** the signed-in owner on a computer, **When** they click Record and allow microphone access,
   **Then** recording works as in User Story 1, and the transcript is filed in the same month folder and
   archive as phone recordings.
3. **Given** the Transcripts view on a wide screen, **When** the owner selects a transcript, **Then** the
   list and the selected transcript's text are shown side by side.
4. **Given** a transcript is open in a browser that has no share sheet, **When** the owner wants to use
   the text elsewhere, **Then** Copy and Download (as a `.txt` file) are offered instead of Share.
5. **Given** desktop Chrome or Edge, **When** the owner chooses the browser's Install option, **Then** the
   app can be installed as a desktop app window (optional convenience; the website works without it).

---

### User Story 4 - Browse past transcripts by month (Priority: P2)

The owner opens the **Transcripts** tab, sees the months that have transcripts (newest first), picks a
month, sees that month's transcripts sorted by date and time (newest first), and opens one to read,
copy, or share it.

**Why this priority**: Saving to storage already delivers value; browsing in-app is a convenience.

**Independent Test**: With transcripts in two different months, verify both months are listed, each
month lists only its own transcripts in date order, and a transcript opens with its full text.

**Acceptance Scenarios**:

1. **Given** transcripts exist for 2026-10 and 2026-11, **When** the owner opens Transcripts, **Then**
   2026-11 is listed above 2026-10.
2. **Given** a month with several transcripts, **When** it is opened, **Then** transcripts appear sorted
   by recording date/time, newest first.
3. **Given** a transcript is open, **When** the owner taps Copy or Share, **Then** the text is copied or
   handed to the device's share sheet (where the browser provides one; see User Story 3).

---

### User Story 5 - Recordings survive interruptions (Priority: P3)

If the network drops or the app is closed after recording, already-captured audio is not lost: it is
kept on the device and uploaded the next time the app is opened. A failed transcription can be retried.

**Why this priority**: Conversations cannot be re-recorded; losing one is costly, but it is a less
common path.

**Independent Test**: Record with the phone in airplane mode, stop, re-enable the network, reopen the
app, and confirm the recording uploads and is transcribed.

**Acceptance Scenarios**:

1. **Given** a recording finished while offline, **When** the app is reopened online, **Then** pending
   audio uploads automatically and transcription proceeds.
2. **Given** a transcription failed, **When** the owner taps Retry, **Then** transcription is attempted
   again without re-uploading audio.

---

### Edge Cases

- Microphone permission denied → clear message explaining how to enable it: in iPhone Settings on the
  phone; on a computer, through the browser's site-permission control and, on a Mac, System Settings →
  Privacy & Security → Microphone.
- Phone screen locks or app is backgrounded during recording → the app keeps the screen awake while
  recording where the device supports it, and warns the owner that iPhone may stop recording in the
  background.
- Laptop sleeps or its lid is closed during recording → audio captured up to that point is kept and
  uploaded, and the owner is told the recording stopped.
- Computer has several microphones → the system's default input device is used (choosing a microphone
  in the app is out of scope for v1).
- Very short recording (< 1 second) → discarded with a message; nothing is sent for transcription.
- Silence or unintelligible audio → a transcript is still saved (possibly empty) with a note.
- Two recordings started in the same second (on the same or different devices) → both are saved; names
  stay unique.
- Recording made just before midnight at month end → filed under the month in which recording started,
  in the recording device's local time zone.
- Signed-out or expired session → owner is asked to sign in again; pending audio is kept.
- Transcription provider error or rate limit → retried automatically a few times, then marked Failed
  with a Retry option.
- Upload that exceeds the size limit → rejected by the system before any transcription cost occurs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST be usable as a website in current desktop and mobile browsers at a single
  web address (the same URL on every device), and MUST be installable to the iPhone home screen,
  launching full-screen with its own name and icon.
- **FR-002**: The system MUST require sign-in before recording or viewing transcripts; accounts are
  created by the administrator only (no public sign-up).
- **FR-003**: Users MUST be able to start, pause, resume, and stop an audio recording from the device's
  microphone, with a visible elapsed-time indicator.
- **FR-004**: The system MUST support recordings of at least 2 hours.
- **FR-005**: While recording, the system MUST upload each finished audio part in the background as
  soon as it is closed, without interrupting the recording. On stop, it MUST upload the final part
  and then start transcription automatically, without further user action. Transcription starts only
  after all parts are uploaded.
- **FR-006**: *Superseded by [002 FR-001](../002-openrouter-transcription/spec.md)*: recordings are
  transcribed through OpenRouter with a configurable model (initially MAI-Transcribe 2).
- **FR-007**: The system MUST save each transcript as a plain-text file in cloud storage, inside a
  folder per month (`YYYY-MM`), with a file name beginning `YYYY-MM-DD_HH-MM-SS` (recording start, local
  time of the recording device) so files sort chronologically.
- **FR-008**: Each transcript file MUST include the recording's start date/time, duration, and the text.
- **FR-009**: The app MUST show transcription status for each recording made on the device
  (uploading, transcribing, done, failed).
- **FR-010**: Users MUST be able to list months, list the transcripts in a month sorted by date (newest
  first), and read, copy, and share a transcript. Where the browser has no share sheet, Download (as a
  `.txt` file) MUST be offered instead of Share.
- **FR-011**: Audio captured but not yet uploaded (including parts whose background upload failed
  during recording) MUST be kept on the device and uploaded later; a part is removed from the device
  only after its upload succeeds.
- **FR-012**: Users MUST be able to retry a failed transcription.
- **FR-013**: Raw audio MUST be deleted automatically after a configurable retention period (default 30
  days); transcripts MUST be kept until deleted by the owner.
- **FR-014**: The system MUST reject uploads larger than the per-file limit and recordings with an
  unreasonable number of parts, before transcription costs are incurred.
- **FR-015**: All cloud infrastructure MUST be reproducible from code with a single deploy command.
- **FR-016**: The layout MUST adapt from phone width (about 375 px) to desktop width (1280 px and wider)
  with no horizontal scrolling, and every action MUST be usable with a mouse and keyboard as well as by
  touch.
- **FR-017**: Recordings made on any device MUST go to the same shared transcript archive and follow the
  same folder and file naming; the stored transcript does not depend on which device recorded it.

### Key Entities

- **Recording**: one conversation captured on a device (phone or computer). Attributes: id, start time
  (with local time zone offset), duration, ordered list of audio parts, optional title, status.
- **Audio Part**: a contiguous chunk of a recording (limits each file to a size the transcription
  service accepts). Attributes: recording id, index, format, size.
- **Transcript**: the text result of a recording. Attributes: month folder, file name (date-time
  prefixed), start time, duration, model used, text.
- **Status**: the processing state of a recording (`transcribing`, `done`, `failed`) with the
  transcript location or an error message.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From tapping Stop on a 10-minute recording with a good connection, the transcript is
  available in under 3 minutes.
- **SC-002**: A 2-hour recording produces one complete transcript covering the whole conversation.
- **SC-003**: 100% of transcripts are filed in the correct month folder and appear in date order
  when the folder is listed.
- **SC-004**: The owner can go from opening the home-screen icon to recording in under 5 seconds
  (when already signed in).
- **SC-005**: No recording is lost when the network is unavailable at the time recording stops.
- **SC-006**: Idle monthly infrastructure cost (no usage) is under US$1, excluding transcription usage.
- **SC-007**: The same web address works end to end (sign in → record → transcript saved and readable)
  in iPhone Safari and in current desktop Chrome and Safari on macOS.

## Assumptions

- Single owner (personal tool); the administrator may invite a small number of trusted users, who all
  share the same transcript archive.
- Supported browsers: iPhone Safari on iOS 17+ (primary recording device, installable to the home
  screen); current desktop Chrome, Edge, and Safari 17+ on macOS (full support); Firefox and other
  browsers on a best-effort basis.
- One web address serves every device; there is no separate desktop site and no device-specific
  redirect.
- On iPhone, the app must stay in the foreground with the screen on while recording; iOS web apps cannot
  record reliably in the background. This is a platform limitation and is communicated in the app. On a
  computer, the browser tab must stay open and the computer awake.
- Speaker labels (who said what) were out of scope for v1. 002 adds them, numbered per 5-minute section
  (002 User Story 5).
- Transcript language is auto-detected.
- Time zone for folder/file naming is the recording device's local time zone at recording start.
- The owner provides an AWS account and an OpenRouter API key with available credits (002).
