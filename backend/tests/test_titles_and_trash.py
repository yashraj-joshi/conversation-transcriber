"""Spec 004: deleted transcripts (trash) and AI titles/summaries."""
import json
import unittest
from datetime import datetime, timezone

import fakes
from fakes import FakeS3, FakeSSM, FakeTranscriber
import api
import core
import transcriber
from openrouter_client import OpenRouterError

RID = "3f2c9a1b-1234-4abc-8def-0123456789ab"
NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
KEY = "transcripts/2026-11/2026-11-11_14-30-05_3f2c9a1b.txt"
TEXT = ("Recorded: 2026-11-11 14:30:05 (UTC-08:00)\nDuration: 00:05:00\nModel: m\nVocabulary: none\n"
        "Cost: US$0.0100\nRecording ID: " + RID + "\n\nWe moved the FastAPI service to Fargate.\n")


def chat_reply(title="FastAPI Moves to Fargate", summary="The team moved the service.", cost=0.0001):
    return {"choices": [{"message": {"content": json.dumps({"title": title, "summary": summary})}}],
            "usage": {"cost": cost}}


class CoreTests(unittest.TestCase):
    def test_trash_keys(self):
        self.assertEqual(core.trash_key(KEY), "trash/" + KEY)
        self.assertEqual(core.original_key("trash/" + KEY), KEY)
        self.assertEqual(core.validate_readable_key("trash/" + KEY), "trash/" + KEY)
        for bad in ["trash/audio/x.wav", "trash/" + KEY + "/..", "trash/transcripts/../x.txt", "audio/x"]:
            with self.assertRaises(core.ValidationError):
                core.validate_readable_key(bad)
        self.assertEqual(core.purge_date(NOW).isoformat(), "2027-02-12T12:00:00+00:00")

    def test_header_set_and_parse(self):
        text = core.set_header_fields("Title: Mine\n" + TEXT, {"AI title": "T", "Summary": "S"})
        self.assertTrue(text.startswith("Title: Mine\nAI title: T\nSummary: S\nRecorded:"))
        again = core.set_header_fields(text, {"AI title": "T2", "Summary": "S2"})
        self.assertEqual(again.count("AI title:"), 1)
        fields = core.parse_header(again)
        self.assertEqual((fields["AI title"], fields["Summary"]), ("T2", "S2"))
        self.assertEqual(core.display_title(fields), "Mine")
        self.assertEqual(core.display_title(core.parse_header(core.set_header_fields(TEXT, {"AI title": "X"}))), "X")
        self.assertTrue(core.split_transcript(again)[1].startswith("We moved"))

    def test_summary_request_and_parse(self):
        p = core.build_summary_request(" anthropic/claude-haiku-5.5 ", "body", "deny")
        self.assertEqual(p["model"], "anthropic/claude-haiku-5.5")
        self.assertEqual(p["response_format"]["json_schema"]["schema"]["required"], ["title", "summary"])
        self.assertEqual(p["provider"], {"data_collection": "deny"})
        self.assertIn("Transcript:\n\nbody", p["messages"][1]["content"])
        long = core.build_summary_request("m", "x" * (core.MAX_SUMMARY_INPUT_CHARS + 10), "")
        self.assertTrue(long["messages"][1]["content"].endswith("[…truncated]"))
        self.assertEqual(core.parse_summary_response(chat_reply("  “Quoted” Title. ", "S " * 3)),
                         ("“Quoted” Title", "S S S", 0.0001))
        fenced = {"choices": [{"message": {"content": "```json\n{\"title\": \"A\", \"summary\": \"B\"}\n```"}}]}
        self.assertEqual(core.parse_summary_response(fenced), ("A", "B", None))
        title, _, _ = core.parse_summary_response(chat_reply("w " * 200))
        self.assertLessEqual(len(title), core.MAX_AI_TITLE_LENGTH)
        for bad in [{}, {"choices": [{"message": {"content": "no json"}}]}, chat_reply(title="")]:
            with self.assertRaises(ValueError):
                core.parse_summary_response(bad)

    def test_has_speech(self):
        self.assertFalse(core.has_speech("(No speech was detected in this recording.)\n"))
        self.assertFalse(core.has_speech("  "))
        self.assertTrue(core.has_speech("hello"))


def call(s3, route, body=None, query=None):
    event = {"routeKey": route, "body": json.dumps(body) if body is not None else None,
             "queryStringParameters": query,
             "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u"}}}}}
    resp = api.handler(event, None, api.Deps(s3=s3, bucket="b", now=lambda: NOW))
    return resp["statusCode"], json.loads(resp["body"])


class TrashApiTests(unittest.TestCase):
    def seed(self):
        s3 = FakeS3()
        s3.put_object(Bucket="b", Key=KEY, Body=core.set_header_fields(TEXT, {"AI title": "Fargate move", "Summary": "S."}),
                      Metadata={"recording-id": RID})
        for k in [f"audio/{RID}/part-000.wav", f"audio/{RID}/manifest.json", f"work/{RID}/part-000.json",
                  "audio/aaaaaaaa-1234-4abc-8def-0123456789ab/part-000.wav"]:
            s3.put_object(Bucket="b", Key=k, Body=b"x")
        return s3

    def test_list_includes_titles_and_summaries(self):
        s3 = self.seed()
        s3.put_object(Bucket="b", Key="transcripts/2026-11/2026-11-12_09-00-00_0c1d2e3f.txt",
                      Body="Title: Mine\nRecorded: x\n\nbody")
        code, body = call(s3, "GET /transcripts", query={"month": "2026-11"})
        self.assertEqual([(i["title"], i["summary"]) for i in body["items"]], [("Mine", None), ("Fargate move", "S.")])

    def test_delete_list_restore(self):
        s3 = self.seed()
        code, body = call(s3, "POST /transcripts/delete", {"key": KEY})
        self.assertEqual((code, body["key"], body["recordingId"]), (200, "trash/" + KEY, RID))
        self.assertEqual(body["removedAudioObjects"], 3)
        self.assertNotIn(KEY, s3.objects)
        self.assertNotIn(f"audio/{RID}/part-000.wav", s3.objects)
        self.assertIn("audio/aaaaaaaa-1234-4abc-8def-0123456789ab/part-000.wav", s3.objects)  # other recordings untouched
        self.assertEqual(call(s3, "GET /transcripts", query={"month": "2026-11"})[1]["items"], [])

        code, body = call(s3, "GET /transcripts/deleted")
        item = body["items"][0]
        self.assertEqual((item["key"], item["originalKey"], item["title"]), ("trash/" + KEY, KEY, "Fargate move"))
        self.assertEqual((item["deletedAt"], item["purgeAt"]), ("2026-11-14T12:00:00Z", "2027-02-12T12:00:00Z"))
        self.assertEqual(call(s3, "GET /transcript", query={"key": "trash/" + KEY})[0], 200)

        original = s3.objects["trash/" + KEY]
        code, body = call(s3, "POST /transcripts/restore", {"key": "trash/" + KEY})
        self.assertEqual((code, body["key"]), (200, KEY))
        self.assertEqual(s3.objects[KEY], original)                      # byte-identical (SC-001)
        self.assertEqual(s3.metadata[KEY]["recording-id"], RID)
        self.assertEqual(call(s3, "GET /transcripts/deleted")[1]["items"], [])

    def test_restore_conflict_and_errors(self):
        s3 = self.seed()
        call(s3, "POST /transcripts/delete", {"key": KEY})
        s3.put_object(Bucket="b", Key=KEY, Body=b"new")
        self.assertEqual(call(s3, "POST /transcripts/restore", {"key": "trash/" + KEY})[0], 409)
        self.assertEqual(s3.objects[KEY], b"new")
        self.assertEqual(call(s3, "POST /transcripts/delete", {"key": "audio/x"})[0], 400)
        self.assertEqual(call(s3, "POST /transcripts/delete",
                              {"key": "transcripts/2026-11/2026-11-01_00-00-00_00000000.txt"})[0], 404)
        self.assertEqual(call(s3, "POST /transcripts/restore", {"key": KEY})[0], 400)


class SummaryTranscriberTests(unittest.TestCase):
    def deps(self, s3, chat):
        transcriber._api_key_cache.clear()
        fake = FakeTranscriber(lambda p: {"text": "We moved the FastAPI service to Fargate.", "usage": {"cost": 0.01}})
        fake.chat = chat
        cfg = transcriber.Config(bucket="b", model_param="/m", api_key_param="/k", vocabulary_key="v",
                                 summary_model_param="/s")
        ssm = FakeSSM({"/m": "microsoft/mai-transcribe-2", "/k": "sk-or-1", "/s": "anthropic/claude-haiku-5.5"})
        return transcriber.Deps(s3=s3, ssm=ssm, client_factory=lambda k: fake, config=cfg, now=lambda: NOW), fake

    def seed(self, s3):
        part = core.part_key(RID, 0, "wav")
        s3.put_object(Bucket="b", Key=part, Body=b"RIFF")
        req = core.validate_complete_request({"startedAt": "2026-11-11T22:30:05Z", "tzOffsetMinutes": -480,
                                              "durationSeconds": 300, "partCount": 1}, NOW)
        s3.put_object(Bucket="b", Key=core.manifest_key(RID), Body=json.dumps(core.build_manifest(
            RID, req, [{"index": 0, "key": part, "contentType": "audio/wav"}], "u", NOW)))
        return {"Records": [{"s3": {"object": {"key": core.manifest_key(RID)}}}]}

    def test_title_and_summary_added(self):
        s3 = FakeS3()
        seen = []
        deps, _ = self.deps(s3, lambda p: seen.append(p) or chat_reply())
        transcriber.handler(self.seed(s3), None, deps)
        text = s3.objects[KEY].decode()
        self.assertTrue(text.startswith("AI title: FastAPI Moves to Fargate\nSummary: The team moved the service.\n"))
        self.assertIn("Cost: US$0.0101", text)
        self.assertEqual(seen[0]["model"], "anthropic/claude-haiku-5.5")
        self.assertIn("FastAPI service to Fargate", seen[0]["messages"][1]["content"])

    def test_summary_failure_keeps_transcript(self):
        s3 = FakeS3()

        def boom(p):
            raise OpenRouterError(402, "Insufficient credits")

        deps, _ = self.deps(s3, boom)
        transcriber.handler(self.seed(s3), None, deps)
        text = s3.objects[KEY].decode()
        self.assertNotIn("AI title:", text)
        self.assertIn("Cost: US$0.0100", text)
        self.assertEqual(json.loads(s3.objects[core.status_key(RID)])["state"], "done")

    def test_retitle_backfill(self):
        s3 = FakeS3()
        s3.put_object(Bucket="b", Key=KEY, Body=TEXT, Metadata={"recording-id": RID})
        other = "transcripts/2026-11/2026-11-12_09-00-00_0c1d2e3f.txt"
        s3.put_object(Bucket="b", Key=other, Body="AI title: Done\nRecorded: x\n\nbody")
        deps, _ = self.deps(s3, lambda p: chat_reply())
        out = transcriber.handler({"action": "retitle", "month": "2026-11"}, None, deps)
        self.assertEqual((out["updated"], out["skipped"]), ([KEY], [other]))
        text = s3.objects[KEY].decode()
        self.assertTrue(text.startswith("AI title: FastAPI Moves to Fargate\n"))
        self.assertIn("Cost: US$0.0101", text)
        self.assertEqual(s3.metadata[KEY]["recording-id"], RID)
        self.assertTrue(text.endswith("We moved the FastAPI service to Fargate.\n"))


if __name__ == "__main__":
    unittest.main()
