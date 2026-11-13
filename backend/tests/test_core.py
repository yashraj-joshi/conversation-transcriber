import unittest
from datetime import datetime, timezone

import fakes  # noqa: F401  (sets sys.path)
import core

RID = "3f2c9a1b-1234-4abc-8def-0123456789ab"
NOW = datetime(2026, 11, 11, 23, 0, 0, tzinfo=timezone.utc)


class KeyTests(unittest.TestCase):
    def test_transcript_key_uses_local_time_and_month(self):
        started = core.parse_started_at("2026-11-11T22:30:05.120Z")
        self.assertEqual(
            core.transcript_key(RID, started, -480),
            "transcripts/2026-11/2026-11-11_14-30-05_3f2c9a1b.txt",
        )

    def test_month_boundary_uses_local_start_month(self):
        # 2026-12-01 05:59 UTC is still 2026-11-30 23:59 in UTC-06:00
        started = core.parse_started_at("2026-12-01T05:59:30Z")
        self.assertTrue(core.transcript_key(RID, started, -360).startswith("transcripts/2026-11/2026-11-30_23-59-30"))

    def test_keys_sort_chronologically(self):
        a = core.transcript_key(RID, core.parse_started_at("2026-11-02T09:00:00Z"), 0)
        b = core.transcript_key(RID, core.parse_started_at("2026-11-10T08:00:00Z"), 0)
        self.assertLess(a, b)

    def test_part_keys(self):
        self.assertEqual(core.part_key(RID, 7, "wav"), f"audio/{RID}/part-007.wav")
        self.assertEqual(core.parse_part_key(f"audio/{RID}/part-007.wav"), (7, "wav"))
        self.assertIsNone(core.parse_part_key(f"audio/{RID}/manifest.json"))
        self.assertIsNone(core.parse_part_key(f"audio/{RID}/part-007.mp4"))

    def test_recording_id_validation(self):
        self.assertEqual(core.validate_recording_id(RID), RID)
        for bad in [None, "", "../x", RID.upper(), "3f2c9a1b-1234-1abc-8def-0123456789ab"]:
            with self.assertRaises(core.ValidationError):
                core.validate_recording_id(bad)

    def test_manifest_key_roundtrip(self):
        self.assertEqual(core.recording_id_from_manifest_key(core.manifest_key(RID)), RID)


class ValidationTests(unittest.TestCase):
    def test_upload_request_wav_only(self):
        req = core.validate_upload_request({"recordingId": RID, "index": 0, "contentType": "audio/wav"})
        self.assertEqual(req["key"], f"audio/{RID}/part-000.wav")
        self.assertEqual(req["contentType"], "audio/wav")
        for ct in ["audio/mp4", "audio/webm;codecs=opus", "video/mp4", None]:
            with self.assertRaises(core.ValidationError):
                core.validate_upload_request({"recordingId": RID, "index": 0, "contentType": ct})

    def test_upload_index_bounds(self):
        core.validate_upload_request({"recordingId": RID, "index": core.MAX_PARTS - 1, "contentType": "audio/wav"})
        for idx in [-1, core.MAX_PARTS, "1", True, 1.5]:
            with self.assertRaises(core.ValidationError):
                core.validate_upload_request({"recordingId": RID, "index": idx, "contentType": "audio/wav"})

    def test_three_hour_cap(self):
        self.assertEqual(core.MAX_DURATION_SECONDS, 3 * 3600)
        self.assertEqual(core.MAX_PARTS, 36)

    def test_limits_fit_provider(self):
        wav_bytes = core.PART_SECONDS * 16000 * 2 + 44
        self.assertLess(wav_bytes, core.MAX_PART_BYTES)
        self.assertLess(core.MAX_PART_BYTES * 4 / 3, 25 * 1024 * 1024)
        self.assertEqual(core.MAX_PARTS * core.PART_SECONDS, core.MAX_DURATION_SECONDS)

    def _complete(self, **over):
        body = {"startedAt": "2026-11-11T22:30:05.120Z", "tzOffsetMinutes": -480,
                "durationSeconds": 61.5, "partCount": 1, "title": "  Weekly   sync "}
        body.update(over)
        return core.validate_complete_request(body, NOW)

    def test_complete_request(self):
        req = self._complete()
        self.assertEqual(req["title"], "Weekly sync")
        self.assertEqual(req["partCount"], 1)
        self.assertEqual(req["startedAt"], "2026-11-11T22:30:05.120Z")

    def test_complete_request_rejects(self):
        for over in [{"startedAt": "2026-11-12T23:00:00Z"}, {"startedAt": "2026-11-11T22:30:05"},
                     {"tzOffsetMinutes": 900}, {"durationSeconds": 0}, {"durationSeconds": 10801},
                     {"partCount": 0}, {"partCount": core.MAX_PARTS + 1}, {"title": "x" * 121}]:
            with self.subTest(over=over), self.assertRaises(core.ValidationError):
                self._complete(**over)

    def test_match_parts(self):
        keys = [f"audio/{RID}/part-000.wav", f"audio/{RID}/part-002.wav", f"audio/{RID}/manifest.json"]
        parts, missing = core.match_parts(keys, 3)
        self.assertEqual([p["index"] for p in parts], [0, 2])
        self.assertEqual(missing, [1])

    def test_validate_manifest(self):
        parts, _ = core.match_parts([f"audio/{RID}/part-001.wav", f"audio/{RID}/part-000.wav"], 2)
        req = self._complete(partCount=2)
        meta = core.validate_manifest(core.build_manifest(RID, req, parts, "sub", NOW))
        self.assertEqual([p["index"] for p in meta["parts"]], [0, 1])
        bad = core.build_manifest(RID, req, parts[:1], "sub", NOW)
        with self.assertRaises(core.ValidationError):
            core.validate_manifest(bad)


class VocabularyTests(unittest.TestCase):
    def test_parse(self):
        text = "# comment\n\nFastAPI\n  pgvector  \nfastapi\nC#\n401(k)\n" + "x" * 101 + "\nRoute  53\n"
        terms, skipped = core.parse_vocabulary(text)
        self.assertEqual(terms, ["FastAPI", "pgvector", "C#", "401(k)", "Route 53"])
        self.assertEqual([r for _, r in skipped], ["duplicate", "longer than 100 characters"])

    def test_cap(self):
        terms, skipped = core.parse_vocabulary("\n".join(f"t{i}" for i in range(1005)))
        self.assertEqual(len(terms), core.MAX_KEYTERMS)
        self.assertEqual(len(skipped), 5)

    def test_repo_vocabulary_file_is_valid(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "vocabulary.txt")
        with open(path, encoding="utf-8") as fh:
            terms, skipped = core.parse_vocabulary(fh.read())
        self.assertGreater(len(terms), 300)
        self.assertEqual(skipped, [])
        for term in ["FastAPI", "C#", ".NET Core", "401(k)", "SAA-C03", "Google Drive"]:
            self.assertIn(term, terms)


class RequestTests(unittest.TestCase):
    def test_build_request(self):
        p = core.build_transcription_request(" microsoft/mai-transcribe-2 ", "QUJD", "wav", ["FastAPI"], "deny")
        self.assertEqual(p, {
            "model": "microsoft/mai-transcribe-2",
            "input_audio": {"data": "QUJD", "format": "wav"},
            "response_format": "json",
            "keyterms": ["FastAPI"],
            "provider": {"data_collection": "deny"},
        })

    def test_build_request_without_optional(self):
        p = core.build_transcription_request("m", "QUJD", "wav", [], "")
        self.assertNotIn("keyterms", p)
        self.assertNotIn("provider", p)
        with self.assertRaises(core.ValidationError):
            core.build_transcription_request("", "QUJD", "wav", [], "deny")

    def test_error_messages(self):
        self.assertIn("insufficient credits", core.error_message(402, "", "m"))
        self.assertIn("'bad/model'", core.error_message(404, "nope", "bad/model"))
        self.assertIn("timed out", core.error_message(524, "", "m"))
        self.assertIn("network", core.error_message(None, "", "m"))
        self.assertTrue(core.is_retryable(529))
        self.assertFalse(core.is_retryable(400))


class SpeakerTests(unittest.TestCase):
    def test_request_with_diarization(self):
        p = core.build_transcription_request("m", "QUJD", "wav", [], "deny", diarize=True)
        self.assertTrue(p["diarize"])
        self.assertEqual(p["response_format"], "verbose_json")
        self.assertEqual(p["timestamp_granularities"], ["segment"])
        self.assertEqual(p["provider"], {"data_collection": "deny",
                                         "options": {"azure": {"diarization": {"enabled": True}}}})
        plain = core.drop_diarization(p)
        self.assertEqual(plain, {"model": "m", "input_audio": {"data": "QUJD", "format": "wav"},
                                 "response_format": "json", "provider": {"data_collection": "deny"}})
        self.assertNotIn("provider", core.drop_diarization(
            core.build_transcription_request("m", "QUJD", "wav", [], "", diarize=True)))

    def test_speaker_name(self):
        cases = [({"speaker": 1}, "Speaker 1"), ({"speaker": "2"}, "Speaker 2"),
                 ({"speaker": "speaker_3"}, "Speaker 3"), ({"speaker": "Guest-4"}, "Speaker 4"),
                 ({"speaker_label": "Alice", "speaker": 0}, "Alice"), ({"speaker": None}, None),
                 ({}, None), ({"speaker": True}, None)]
        for seg, expected in cases:
            self.assertEqual(core.speaker_name(seg), expected, seg)

    def test_turns_merge_and_offset(self):
        segs = core.compact_segments([
            {"start": 0.0, "text": "Hi.", "speaker": 1},
            {"start": 2.5, "text": " How are  you?", "speaker": 1},
            {"start": 5.0, "text": "Good.", "speaker": 2},
            {"start": 6.0, "text": "   ", "speaker": 2},
            {"start": 7.0, "text": "And you?", "speaker": 2},
        ])
        body = core.part_body({"text": "ignored", "segments": segs}, 2)
        self.assertEqual(body, "[00:10:00] Speaker 1: Hi. How are you?\n\n[00:10:05] Speaker 2: Good. And you?")

    def test_part_body_falls_back_to_text(self):
        self.assertEqual(core.part_body({"text": " plain ", "segments": []}, 0), "plain")
        segs = core.compact_segments([{"start": 0, "text": "no speaker"}])
        self.assertEqual(core.part_body({"text": "plain", "segments": segs}, 0), "plain")

    def test_speakers_status(self):
        self.assertIsNone(core.speakers_status(False, [True]))
        self.assertIn("5-minute section", core.speakers_status(True, [True, False]))
        self.assertEqual(core.speakers_status(True, [False]), "not returned by the model")


class RenderTests(unittest.TestCase):
    def test_render(self):
        meta = {"recordingId": RID, "startedAt": core.parse_started_at("2026-11-11T22:30:05Z"),
                "tzOffsetMinutes": -480, "durationSeconds": 2537, "title": "Weekly sync"}
        text = core.render_transcript(meta, ["Hello there.", " ", "Second part."],
                                      "microsoft/mai-transcribe-2", "313 terms", 0.0123, "labelled")
        self.assertEqual(text, (
            "Title: Weekly sync\nRecorded: 2026-11-11 14:30:05 (UTC-08:00)\nDuration: 00:42:17\n"
            "Model: microsoft/mai-transcribe-2\nVocabulary: 313 terms\nSpeakers: labelled\nCost: US$0.0123\n"
            f"Recording ID: {RID}\n\nHello there.\n\nSecond part.\n"
        ))

    def test_render_empty(self):
        meta = {"recordingId": RID, "startedAt": NOW, "tzOffsetMinutes": 330, "durationSeconds": 3, "title": None}
        text = core.render_transcript(meta, [""], "m", "none")
        self.assertIn("(UTC+05:30)", text)
        self.assertIn("No speech was detected", text)

    def test_vocabulary_status(self):
        self.assertEqual(core.vocabulary_status(0, [True]), "none")
        self.assertEqual(core.vocabulary_status(5, [True, True]), "5 terms")
        self.assertEqual(core.vocabulary_status(5, [False]), "not applied (rejected by provider)")
        self.assertIn("1 of 2 parts", core.vocabulary_status(5, [True, False]))


class ListingTests(unittest.TestCase):
    def test_transcript_item_and_validation(self):
        key = "transcripts/2026-11/2026-11-11_14-30-05_3f2c9a1b.txt"
        self.assertEqual(core.transcript_item(key, 10)["recordedAt"], "2026-11-11 14:30:05")
        self.assertEqual(core.validate_transcript_key(key), key)
        for bad in ["transcripts/../audio/x.txt", "audio/x", "transcripts/2026-11/a.txt"]:
            with self.assertRaises(core.ValidationError):
                core.validate_transcript_key(bad)
        with self.assertRaises(core.ValidationError):
            core.validate_month("2026-13")


if __name__ == "__main__":
    unittest.main()
