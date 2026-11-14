# Feature Specification: Transcribe an Uploaded Audio File

**Feature Branch**: `003-upload-audio-file`

**Created**: 2026-11-13

**Status**: Draft

**Builds on**: [001](../001-record-transcribe-pwa/spec.md) and [002](../002-openrouter-transcription/spec.md).

**Input**: User description: "Add a way to directly upload a file and run the transcription service on it,
instead of only Record and Stop."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Transcribe an existing recording (Priority: P1)

The owner already has audio, such as an iPhone Voice Memo, a meeting recording, or an MP3 someone sent. On
the Record screen they choose **Upload a file** and pick it. The app shows the file's name and length,
pre-fills a title (the file name) and the recording date and time (from the file), and lets the owner
change both. They tap **Transcribe**. From then on it behaves like a finished recording: it uploads, is
transcribed, and is filed in the month folder of the chosen date.

**Why this priority**: This is the whole feature.

**Independent Test**: On a Mac, upload a 7-minute MP3 and a 2-minute M4A. On an iPhone, upload a Voice
Memo from the Files app. Each appears in "On this device", reaches Done, and its transcript is in the month
folder of the chosen date with a header naming the source file.

**Acceptance Scenarios**:

1. **Given** the owner picks a supported audio file, **When** it has been read, **Then** the app shows its
   name and duration, with a title and a recording date and time already filled in and editable.
2. **Given** the owner taps Transcribe, **When** preparation finishes, **Then** the file appears in "On this
   device" with the usual statuses (Uploading → Transcribing → Done) and the usual Retry on failure.
3. **Given** the owner set the recording time to 2 Oct 2026 09:15:00, **When** transcription completes,
   **Then** the transcript is stored in folder `2026-10` with a name starting `2026-10-02_09-15-00`.
4. **Given** a transcript made from an uploaded file, **When** it is opened, **Then** its header includes
   `Source file: <original file name>`.
5. **Given** a file longer than 5 minutes, **When** it is transcribed, **Then** the whole file is covered
   in one transcript, in order (same splitting as recordings).
6. **Given** the owner taps Cancel before Transcribe, **When** they return to the Record screen, **Then**
   nothing is uploaded or stored.

---

### Edge Cases

- Unsupported or corrupt file → a plain message: "This browser can't read this file. Try MP3, M4A, WAV, or
  FLAC." Nothing is uploaded.
- File longer than 3 hours → rejected with a message (same limit as recordings). Shorter than 1 second →
  rejected.
- File larger than 500 MB → rejected before it is read.
- Very long files on iPhone → the browser may run out of memory while reading. The app says so and suggests
  using a computer for files over about an hour.
- Video files (MP4/MOV) → the audio track is used if the browser can decode it.
- A recording is in progress → Upload is unavailable until it stops. While a file is being prepared,
  Record is unavailable.
- The app is closed while a file is being prepared → the partial import is discarded the next time the app
  opens. The owner picks the file again.
- Offline → preparation still works. The upload waits until the device is online (001 FR-011).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Record screen MUST offer "Upload a file" on phone and desktop, using the device's file
  picker (Files app on iPhone).
- **FR-002**: The system MUST accept any audio the browser can decode, including at least MP3, M4A/AAC, WAV,
  and FLAC on iPhone Safari and desktop Chrome/Safari/Edge, up to 500 MB and 3 hours.
- **FR-003**: Before upload, the file MUST be converted to the same format and part size as recordings (002
  FR-007, FR-008), so the transcription service, limits, retries, and costs are identical.
- **FR-004**: The owner MUST be able to set the title and the recording start date and time. The defaults
  are the file name (without extension) and the file's modified time minus its duration. The date and time
  are interpreted in the device's time zone and determine the month folder and file name (001 FR-007).
- **FR-005**: The transcript header MUST include the original file name.
- **FR-006**: Uploaded files MUST appear in "On this device" with the same statuses, Retry, and Remove
  actions as recordings.
- **FR-007**: Recording and file preparation MUST NOT run at the same time.

### Key Entities

- **Recording** (001) gains an optional `sourceName` (the original file name, ≤ 200 characters) and a
  device-only state `importing`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A 10-minute MP3 is prepared in under 15 seconds on a current laptop, and its transcript is
  ready in under 3 minutes on a good connection.
- **SC-002**: Files of at least 60 minutes can be prepared on an iPhone 13 or newer. Files up to 3 hours
  can be prepared on a desktop browser.
- **SC-003**: 100% of transcripts from uploaded files are filed under the month of the chosen date.

## Assumptions

- Conversion happens in the browser, the same way recordings are captured. Server-side conversion would
  need a media toolkit (ffmpeg), which the constitution rules out without a strong reason.
- Because files are converted to WAV, uploading a compressed file sends more data than its original size
  (about 115 MB per hour of audio).
- The file's modified time is only a starting point for the recording date. Many apps set it to the export
  time, so the owner can correct it.
