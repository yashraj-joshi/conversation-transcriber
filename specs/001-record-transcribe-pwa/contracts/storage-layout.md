# Storage Layout Contract (S3 data bucket)

```text
s3://<project>-data-<account-id>/
├── audio/                                   # transient, expires after audio_retention_days (default 30)
│   └── <recordingId>/
│       ├── part-000.mp4
│       ├── part-001.mp4
│       └── manifest.json                    # written last; its creation triggers transcription
├── status/                                  # transient, expires after 90 days
│   └── <recordingId>.json
└── transcripts/                             # retained (bucket versioning on)
    ├── 2026-10/
    │   ├── 2026-10-02_09-15-00_a1b2c3d4.txt
    │   └── 2026-10-28_18-03-44_e5f6a7b8.txt
    └── 2026-11/                             # one folder per month (recording start, local time)
        ├── 2026-11-03_08-00-12_0c1d2e3f.txt
        └── 2026-11-11_14-30-05_3f2c9a1b.txt # name starts with date-time → lexical order = chronological order
```

Rules:

1. Folder: `transcripts/YYYY-MM/`, using the recording **start** time in the recording device's local time zone
   (phone or computer; the layout is the same for every device).
2. File: `YYYY-MM-DD_HH-MM-SS_<first 8 hex chars of recordingId>.txt`.
3. S3 lists keys in UTF-8 binary order, so the S3 console and `aws s3 ls` show files oldest → newest.
   The API returns them newest first.
4. Only the transcriber Lambda writes to `transcripts/` and `status/`. Only presigned POSTs (from the API)
   and the API's manifest write touch `audio/`.
