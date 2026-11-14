import json
import unittest
from datetime import datetime, timezone

import fakes
from fakes import FakeS3
import api
import core

RID = "3f2c9a1b-1234-4abc-8def-0123456789ab"
NOW = datetime(2026, 11, 11, 23, 0, 0, tzinfo=timezone.utc)


def call(s3, route, body=None, path=None, query=None):
    event = {
        "routeKey": route,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path,
        "queryStringParameters": query,
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user-1"}}}},
    }
    resp = api.handler(event, None, api.Deps(s3=s3, bucket="b", now=lambda: NOW))
    return resp["statusCode"], json.loads(resp["body"])


COMPLETE = {"startedAt": "2026-11-11T22:30:05Z", "tzOffsetMinutes": -480, "durationSeconds": 310, "partCount": 2}


class UploadTests(unittest.TestCase):
    def test_presigned_post_is_bounded(self):
        s3 = FakeS3()
        code, body = call(s3, "POST /uploads", {"recordingId": RID, "index": 1, "contentType": "audio/wav"})
        self.assertEqual(code, 200)
        self.assertEqual(body["key"], f"audio/{RID}/part-001.wav")
        self.assertEqual(body["fields"]["Content-Type"], "audio/wav")
        self.assertEqual(body["maxBytes"], core.MAX_PART_BYTES)

    def test_rejects_non_wav_and_bad_ids(self):
        s3 = FakeS3()
        for body in [{"recordingId": RID, "index": 0, "contentType": "audio/mp4"},
                     {"recordingId": "x", "index": 0, "contentType": "audio/wav"},
                     {"recordingId": RID, "index": 36, "contentType": "audio/wav"}]:
            self.assertEqual(call(s3, "POST /uploads", body)[0], 400)


class CompleteTests(unittest.TestCase):
    def test_missing_parts_is_409(self):
        s3 = FakeS3()
        s3.put_object(Bucket="b", Key=core.part_key(RID, 0, "wav"), Body=b"a")
        code, body = call(s3, "POST /recordings/{id}/complete", COMPLETE, path={"id": RID})
        self.assertEqual((code, body["missing"]), (409, [1]))
        self.assertNotIn(core.manifest_key(RID), s3.objects)

    def test_writes_manifest(self):
        s3 = FakeS3(page_size=1)  # exercises pagination
        for i in range(2):
            s3.put_object(Bucket="b", Key=core.part_key(RID, i, "wav"), Body=b"a")
        code, body = call(s3, "POST /recordings/{id}/complete", COMPLETE, path={"id": RID})
        self.assertEqual((code, body["state"]), (202, "transcribing"))
        manifest = json.loads(s3.objects[core.manifest_key(RID)])
        self.assertEqual([p["key"] for p in manifest["parts"]],
                         [core.part_key(RID, 0, "wav"), core.part_key(RID, 1, "wav")])
        self.assertEqual(manifest["submittedBy"], "user-1")
        self.assertIsNone(manifest["sourceName"])
        core.validate_manifest(manifest)

    def test_done_returns_200_without_rewrite(self):
        s3 = FakeS3()
        s3.put_object(Bucket="b", Key=core.status_key(RID), Body=json.dumps({"recordingId": RID, "state": "done"}))
        code, body = call(s3, "POST /recordings/{id}/complete", COMPLETE, path={"id": RID})
        self.assertEqual((code, body["state"]), (200, "done"))
        self.assertNotIn(core.manifest_key(RID), s3.objects)


class ReadTests(unittest.TestCase):
    def test_status_pending_when_absent(self):
        code, body = call(FakeS3(), "GET /recordings/{id}", path={"id": RID})
        self.assertEqual((code, body["state"]), (200, "pending"))

    def test_months_and_items_newest_first(self):
        s3 = FakeS3(page_size=2)
        keys = ["transcripts/2026-10/2026-10-02_09-15-00_a1b2c3d4.txt",
                "transcripts/2026-11/2026-11-03_08-00-12_0c1d2e3f.txt",
                "transcripts/2026-11/2026-11-11_14-30-05_3f2c9a1b.txt",
                "transcripts/notes/readme.txt"]
        for k in keys:
            s3.put_object(Bucket="b", Key=k, Body=b"hello")
        self.assertEqual(call(s3, "GET /transcripts/months")[1]["months"], ["2026-11", "2026-10"])
        code, body = call(s3, "GET /transcripts", query={"month": "2026-11"})
        self.assertEqual([i["name"][:10] for i in body["items"]], ["2026-11-11", "2026-11-03"])
        code, body = call(s3, "GET /transcript", query={"key": keys[2]})
        self.assertEqual((code, body["text"]), (200, "hello"))

    def test_transcript_errors(self):
        s3 = FakeS3()
        self.assertEqual(call(s3, "GET /transcript", query={"key": "audio/../secret"})[0], 400)
        self.assertEqual(call(s3, "GET /transcript",
                              query={"key": "transcripts/2026-11/2026-11-11_14-30-05_3f2c9a1b.txt"})[0], 404)
        self.assertEqual(call(s3, "GET /transcripts", query={"month": "bad"})[0], 400)

    def test_unknown_route_and_bad_json(self):
        s3 = FakeS3()
        self.assertEqual(call(s3, "DELETE /x")[0], 404)
        event = {"routeKey": "POST /uploads", "body": "{not json"}
        self.assertEqual(api.handler(event, None, api.Deps(s3=s3, bucket="b"))["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
