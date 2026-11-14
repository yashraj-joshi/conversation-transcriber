# Feature Specification: Delete & Restore Transcripts; AI Titles and Summaries

**Feature Branch**: `004-transcript-delete-and-titles`

**Created**: 2026-11-14

**Status**: Draft

**Builds on**: [001](../001-record-transcribe-pwa/spec.md), [002](../002-openrouter-transcription/spec.md),
[003](../003-upload-audio-file/spec.md).

**Input**: User description: "Deleted transcripts should still be recoverable for 90 days and show up in a
Deleted section. There should be a delete option in the Transcripts folder of the app. Instead of showing
just a date and timestamp for each transcript, show the date and a title from a transcript summary,
generated with the cheapest Claude model (Haiku 5.5) through OpenRouter."

## Clarifications

### Session 2026-11-14

- Q: How are deleted transcripts handled? → A: They are recoverable for 90 days in a Deleted section, then
  removed permanently.
- Q: Which model generates titles and summaries? → A: Claude Haiku 5.5 (`anthropic/claude-haiku-5.5`) via
  OpenRouter.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Delete a transcript, and undo it within 90 days (Priority: P1)

The owner opens a transcript in the Transcripts tab and taps **Delete**. After confirming, it disappears
from its month and appears under **Deleted**, along with the date it will be removed for good. Until then
the owner can open it there and tap **Restore** to put it back in its original month folder.

**Why this priority**: The owner currently cannot delete anything from the app, and deleting by mistake must
be recoverable.

**Independent Test**: Delete a transcript, confirm it is gone from its month and listed under Deleted with a
removal date 90 days later, restore it, and confirm it is back in the same month with the same name and
text.

**Acceptance Scenarios**:

1. **Given** an open transcript, **When** the owner taps Delete and confirms, **Then** it leaves its month
   list and appears under Deleted showing "Deleted <date> · removed permanently <date + 90 days>".
2. **Given** the confirmation, **When** the owner cancels, **Then** nothing changes.
3. **Given** a transcript under Deleted, **When** the owner opens it, **Then** its text is readable and a
   Restore button replaces Delete.
4. **Given** the owner taps Restore, **When** it completes, **Then** the transcript is back in its original
   month folder with the same file name and text, and it is no longer under Deleted.
5. **Given** 90 days have passed since deletion, **When** storage is checked, **Then** the transcript is
   gone permanently.
6. **Given** a transcript is deleted, **When** the deletion completes, **Then** that recording's remaining
   raw audio and per-part results are deleted immediately rather than at their 30-day expiry. Restore
   brings back the transcript text only.

---

### User Story 2 - See what each transcript is about (Priority: P1)

In the Transcripts list, each entry shows a **title** and a one- or two-sentence **summary** under it, with
the date and time. Both are generated automatically from the transcript. A title the owner typed when
recording takes precedence over the generated one.

**Why this priority**: A list of timestamps is hard to navigate. Titles make the archive usable.

**Independent Test**: Record a short conversation without typing a title. Within the usual time the list
entry shows a specific title and a short summary, and the transcript file's header contains `AI title:` and
`Summary:` lines.

**Acceptance Scenarios**:

1. **Given** a new transcript, **When** it is saved, **Then** its header has `AI title:` (at most about 10
   words) and `Summary:` (at most 2 sentences) lines, generated from the full transcript.
2. **Given** the owner typed a title when recording, **When** the list is shown, **Then** that title is
   displayed and the summary is still shown.
3. **Given** title generation fails (credits, model error, timeout), **When** the transcript is saved,
   **Then** it is still saved and marked Done, without AI lines. The list falls back to the date and time.
4. **Given** transcripts made before this feature, **When** the owner runs the documented one-off command,
   **Then** they get titles and summaries too.
5. **Given** the summary model setting is changed, **When** the next transcript is saved, **Then** the new
   model is used without a redeploy (same mechanism as the transcription model).

---

### Edge Cases

- The transcript is empty or contains only "(No speech was detected…)" → no AI call; the list shows the date
  and time.
- Restoring when a transcript with the same name already exists in the month → refused with a clear
  message (does not overwrite).
- Deleting from the "On this device" list → that list's **Hide** only clears local history (renamed from
  "Remove" to avoid confusion); deleting the stored transcript is done in the Transcripts tab.
- A device-list entry whose transcript was deleted → it is hidden automatically on that device after delete.
- Uploaded files: the title field starts empty (generated automatically) rather than prefilled with the file
  name. The file name remains in the header as `Source file:`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The transcript viewer MUST offer Delete, with a confirmation step.
- **FR-002**: Deleted transcripts MUST be kept in a separate Deleted area for 90 days and then removed
  permanently and automatically.
- **FR-003**: The Transcripts tab MUST have a Deleted section listing deleted transcripts, newest deletion
  first, each with its deletion date and permanent-removal date.
- **FR-004**: A deleted transcript MUST be viewable and restorable to its original month folder and file
  name. Restore MUST NOT overwrite an existing file.
- **FR-005**: Deleting MUST also delete the recording's raw audio and per-part results.
- **FR-006**: After each transcription, the system MUST generate a title (≤ 100 characters) and a summary
  (≤ 400 characters) from the transcript with the configured summary model, initially
  `anthropic/claude-haiku-5.5`. The model id is stored like the transcription model (SSM, changeable without
  a redeploy).
- **FR-007**: Title or summary failures MUST NOT fail or delay the transcript beyond the generation attempt.
- **FR-008**: List entries MUST show the title (the owner's title if given, otherwise the AI title, otherwise
  the date), the date and time, and the summary.
- **FR-009**: A one-off command MUST add titles and summaries to existing transcripts in a given month.
- **FR-010**: Summary requests MUST use the same privacy routing as transcription (no data collection).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A deleted transcript can be restored, byte-identical, at any time within 90 days.
- **SC-002**: 95% of new transcripts with speech have an AI title and summary.
- **SC-003**: Titles and summaries add less than US$0.01 per transcript-hour (Haiku 5.5: about US$0.004 for
  3 hours).
- **SC-004**: The month list for 50 transcripts loads in under 2 seconds.

## Assumptions

- "Deleted" is shared by all users of the deployment, like the archive.
- Titles and summaries are generated in the transcript's language.
