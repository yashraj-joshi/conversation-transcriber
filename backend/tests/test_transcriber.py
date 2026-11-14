import base64
import json
import unittest
from datetime import datetime, timezone

import fakes
from fakes import FakeS3, FakeSSM, FakeTranscriber
import core
import transcriber
from openrouter_client import OpenRouterError

RID = "3f2c9a1b-1234-4abc-8def-0123456789ab"
NOW = datetime(2026, 11, 11, 23, 0, 0, tzinfo=timezone.utc)
MODEL_PARAM, KEY_PARAM = "/ct/transcription-model", "/ct/openrouter-api-key"


def make_deps(s3, responder, model="microsoft/mai-transcribe-2", key="sk-or-1", parallelism=4, diarize=True):
    transcriber._api_key_cache.clear()
    transcriber._no_keyterms_field.clear()
    fake = FakeTranscriber(responder)
    keys_seen = []

    def factory(api_key):
        keys_seen.append(api_key)
        return fake

    deps = transcriber.Deps(
        s3=s3, ssm=FakeSSM({MODEL_PARAM: model, KEY_PARAM: key}), client_factory=factory,
        config=transcriber.Config(bucket="b", model_param=MODEL_PARAM, api_key_param=KEY_PARAM,
                                  vocabulary_key="config/vocabulary.txt", parallelism=parallelism,
                                  diarize=diarize),
        now=lambda: NOW,
    )
    return deps, fake, keys_seen


def seed(s3, part_count=3, vocabulary="FastAPI\npgvector\n"):
    parts = []
    for i in range(part_count):
        key = core.part_key(RID, i, "wav")
        s3.put_object(Bucket="b", Key=key, Body=f"RIFF-part-{i}".encode())
        parts.append({"index": i, "key": key, "contentType": "audio/wav"})
    if vocabulary is not None:
        s3.put_object(Bucket="b", Key="config/vocabulary.txt", Body=vocabulary.encode())
    req = core.validate_complete_request({"startedAt": "2026-11-11T22:30:05Z", "tzOffsetMinutes": -480,
                                          "durationSeconds": 900, "partCount": part_count}, NOW)
    s3.put_object(Bucket="b", Key=core.manifest_key(RID),
                  Body=json.dumps(core.build_manifest(RID, req, parts, "sub", NOW)).encode())


def part_index(payload):
    return int(base64.b64decode(payload["input_audio"]["data"]).decode().rsplit("-", 1)[1])


def ok(payload):
    return {"text": f"text {part_index(payload)}", "usage": {"cost": 0.001, "seconds": 300}}


def event():
    return {"Records": [{"s3": {"object": {"key": core.manifest_key(RID)}}}]}


TRANSCRIPT = "transcripts/2026-11/2026-11-11_14-30-05_3f2c9a1b.txt"


class TranscriberTests(unittest.TestCase):
    def status(self, s3):
        return json.loads(s3.objects[core.status_key(RID)])

    def test_happy_path(self):
        s3 = FakeS3()
        seed(s3)
        deps, fake, keys = make_deps(s3, ok)
        transcriber.handler(event(), None, deps)

        text = s3.objects[TRANSCRIPT].decode()
        self.assertIn("Model: microsoft/mai-transcribe-2\nVocabulary: 2 terms\n"
                      "Speakers: not returned by the model\nCost: US$0.0030", text)
        self.assertTrue(text.endswith("text 0\n\ntext 1\n\ntext 2\n"))  # spoken order despite parallelism
        self.assertEqual(self.status(s3)["state"], "done")
        self.assertEqual(self.status(s3)["transcriptKey"], TRANSCRIPT)
        self.assertEqual(keys, ["sk-or-1"])
        p = fake.payloads[0]
        self.assertEqual(p["model"], "microsoft/mai-transcribe-2")
        self.assertEqual(p["keyterms"], ["FastAPI", "pgvector"])
        self.assertEqual(p["input_audio"]["format"], "wav")
        self.assertEqual(p["provider"]["data_collection"], "deny")
        self.assertTrue(p["diarize"])
        self.assertEqual(s3.metadata[TRANSCRIPT]["model"], "microsoft/mai-transcribe-2")

    def test_speaker_labels_with_recording_offsets(self):
        s3 = FakeS3()
        seed(s3, part_count=2)

        def diarized(payload):
            i = part_index(payload)
            return {"text": "x", "segments": [
                {"id": 0, "start": 1.0, "end": 2.0, "text": f"Hello from part {i}.", "speaker": 1},
                {"id": 1, "start": 3.0, "end": 4.0, "text": "Reply.", "speaker": 2}]}

        deps, _, _ = make_deps(s3, diarized)
        transcriber.handler(event(), None, deps)
        text = s3.objects[TRANSCRIPT].decode()
        self.assertIn("Speakers: labelled per 5-minute section", text)
        self.assertIn("[00:00:01] Speaker 1: Hello from part 0.\n\n[00:00:03] Speaker 2: Reply.\n\n"
                      "[00:05:01] Speaker 1: Hello from part 1.", text)

    def test_speaker_labels_rejected_falls_back(self):
        s3 = FakeS3()
        seed(s3, part_count=1, vocabulary=None)

        def responder(payload):
            if payload.get("diarize"):
                raise OpenRouterError(400, "diarization not supported")
            return ok(payload)

        deps, fake, _ = make_deps(s3, responder)
        transcriber.handler(event(), None, deps)
        self.assertEqual(self.status(s3)["state"], "done")
        self.assertEqual(len(fake.payloads), 2)
        self.assertEqual(fake.payloads[1]["response_format"], "json")
        self.assertIn("text 0", s3.objects[TRANSCRIPT].decode())

    def test_both_optional_features_dropped_in_order(self):
        s3 = FakeS3()
        seed(s3, part_count=1)
        deps, fake, _ = make_deps(s3, lambda p: (_ for _ in ()).throw(OpenRouterError(400, "bad"))
                                  if ("keyterms" in p or p.get("diarize")) else ok(p))
        transcriber.handler(event(), None, deps)
        self.assertEqual(self.status(s3)["state"], "done")
        self.assertEqual([("keyterms" in p, bool(p.get("diarize"))) for p in fake.payloads],
                         [(True, True), (False, True), (False, False)])

    def test_speaker_labels_disabled(self):
        s3 = FakeS3()
        seed(s3, part_count=1)
        deps, fake, _ = make_deps(s3, ok, diarize=False)
        transcriber.handler(event(), None, deps)
        self.assertNotIn("diarize", fake.payloads[0])
        self.assertNotIn("Speakers:", s3.objects[TRANSCRIPT].decode())

    def test_model_comes_from_ssm(self):
        s3 = FakeS3()
        seed(s3, part_count=1)
        deps, fake, _ = make_deps(s3, ok, model="openai/whisper-1")
        transcriber.handler(event(), None, deps)
        self.assertEqual(fake.payloads[0]["model"], "openai/whisper-1")
        self.assertIn("Model: openai/whisper-1", s3.objects[TRANSCRIPT].decode())

    def test_vocabulary_rejected_falls_back(self):
        s3 = FakeS3()
        seed(s3, part_count=2)

        def responder(payload):
            if "keyterms" in payload:
                raise OpenRouterError(400, "phraseList too long")
            return ok(payload)

        deps, fake, _ = make_deps(s3, responder)
        transcriber.handler(event(), None, deps)
        self.assertIn("Vocabulary: not applied (rejected by provider)", s3.objects[TRANSCRIPT].decode())
        self.assertEqual(self.status(s3)["state"], "done")
        self.assertEqual(len(fake.payloads), 4)

    def test_keyterms_field_rejected_uses_azure_phrase_list(self):
        # Real OpenRouter behaviour for microsoft/mai-transcribe-2 (observed 2026-11-13).
        s3 = FakeS3()
        seed(s3, part_count=3)

        def responder(payload):
            if "keyterms" in payload:
                raise OpenRouterError(400, "The selected model does not support keyterms. Remove the field "
                                           "or choose a model whose provider supports it.")
            return ok(payload)

        deps, fake, _ = make_deps(s3, responder, parallelism=1)
        transcriber.handler(event(), None, deps)
        text = s3.objects[TRANSCRIPT].decode()
        self.assertIn("Vocabulary: 2 terms (as Azure phrase list)", text)
        self.assertEqual(len(fake.payloads), 4)  # one rejection, then the model is remembered
        for p in fake.payloads[1:]:
            self.assertNotIn("keyterms", p)
            self.assertEqual(p["provider"]["options"]["azure"]["phraseList"]["phrases"], ["FastAPI", "pgvector"])

    def test_phrase_list_also_rejected_drops_vocabulary(self):
        s3 = FakeS3()
        seed(s3, part_count=1)

        def responder(payload):
            if "keyterms" in payload:
                raise OpenRouterError(400, "does not support keyterms")
            if payload.get("provider", {}).get("options", {}).get("azure", {}).get("phraseList"):
                raise OpenRouterError(400, "phraseList exceeds 200 phrases")
            return ok(payload)

        deps, fake, _ = make_deps(s3, responder)
        transcriber.handler(event(), None, deps)
        self.assertIn("Vocabulary: not applied (rejected by provider)", s3.objects[TRANSCRIPT].decode())
        self.assertEqual(len(fake.payloads), 3)

    def test_missing_vocabulary_file(self):
        s3 = FakeS3()
        seed(s3, part_count=1, vocabulary=None)
        deps, fake, _ = make_deps(s3, ok)
        transcriber.handler(event(), None, deps)
        self.assertNotIn("keyterms", fake.payloads[0])
        self.assertIn("Vocabulary: none", s3.objects[TRANSCRIPT].decode())

    def test_failure_then_retry_reuses_cached_parts(self):
        s3 = FakeS3()
        seed(s3, part_count=3)

        def flaky(payload):
            if part_index(payload) == 1:
                raise OpenRouterError(402, "Insufficient credits")
            return ok(payload)

        deps, fake, _ = make_deps(s3, flaky, parallelism=1)
        transcriber.handler(event(), None, deps)
        status = self.status(s3)
        self.assertEqual(status["state"], "failed")
        self.assertIn("insufficient credits", status["error"])
        self.assertNotIn(TRANSCRIPT, s3.objects)

        deps2, fake2, _ = make_deps(s3, ok)
        transcriber.handler(event(), None, deps2)
        self.assertEqual(self.status(s3)["state"], "done")
        self.assertEqual([part_index(p) for p in fake2.payloads], [1])  # parts 0 and 2 were cached

    def test_done_is_noop(self):
        s3 = FakeS3()
        seed(s3, part_count=1)
        deps, fake, _ = make_deps(s3, ok)
        transcriber.handler(event(), None, deps)
        transcriber.handler(event(), None, deps)
        self.assertEqual(len(fake.payloads), 1)

    def test_placeholder_key_fails_clearly(self):
        s3 = FakeS3()
        seed(s3, part_count=1)
        deps, fake, _ = make_deps(s3, ok, key="REPLACE_ME")
        transcriber.handler(event(), None, deps)
        self.assertIn("set-openrouter-key.sh", self.status(s3)["error"])
        self.assertEqual(fake.payloads, [])

    def test_unknown_model(self):
        s3 = FakeS3()
        seed(s3, part_count=1)

        def not_found(payload):
            raise OpenRouterError(404, "No endpoints found")

        deps, _, _ = make_deps(s3, not_found, model="nope/model")
        transcriber.handler(event(), None, deps)
        self.assertIn("'nope/model' not found", self.status(s3)["error"])
        self.assertIn(core.part_key(RID, 0, "wav"), s3.objects)  # audio kept for Retry

    def test_ignores_non_manifest_keys(self):
        s3 = FakeS3()
        deps, fake, _ = make_deps(s3, ok)
        out = transcriber.handler({"Records": [{"s3": {"object": {"key": "audio/x/part-000.wav"}}}]}, None, deps)
        self.assertEqual(out, {"results": []})

    def test_url_encoded_key(self):
        s3 = FakeS3()
        seed(s3, part_count=1)
        deps, fake, _ = make_deps(s3, ok)
        ev = {"Records": [{"s3": {"object": {"key": core.manifest_key(RID).replace("/", "%2F")}}}]}
        transcriber.handler(ev, None, deps)
        self.assertEqual(self.status(s3)["state"], "done")


if __name__ == "__main__":
    unittest.main()
