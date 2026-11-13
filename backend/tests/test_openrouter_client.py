import io
import json
import unittest
import urllib.error
from email.message import Message

import fakes  # noqa: F401
from openrouter_client import DEFAULT_URL, OpenRouterClient, OpenRouterError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, message="", retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    return urllib.error.HTTPError(DEFAULT_URL, code, "err", headers, io.BytesIO(body))


class Opener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(json.dumps(outcome).encode())


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []

    def client(self, outcomes):
        self.opener = Opener(outcomes)
        return OpenRouterClient("sk-or-test", opener=self.opener, sleep=self.sleeps.append)

    def test_success_sends_json_with_bearer(self):
        result = self.client([{"text": "hello", "usage": {"cost": 0.001}}]).transcribe({"model": "m"})
        self.assertEqual(result["text"], "hello")
        req = self.opener.requests[0]
        self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/audio/transcriptions")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-or-test")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(req.data), {"model": "m"})

    def test_retries_transient_then_succeeds(self):
        c = self.client([http_error(529, "overloaded"), http_error(429, "slow down", retry_after=5),
                         urllib.error.URLError("reset"), {"text": "ok"}])
        self.assertEqual(c.transcribe({})["text"], "ok")
        self.assertEqual(self.sleeps, [2, 5, 8])

    def test_gives_up_after_max_attempts(self):
        c = self.client([http_error(503)] * 4)
        with self.assertRaises(OpenRouterError) as ctx:
            c.transcribe({})
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(len(self.opener.requests), 4)

    def test_does_not_retry_client_errors(self):
        for code in (400, 401, 402, 404):
            c = self.client([http_error(code, "bad")])
            with self.assertRaises(OpenRouterError) as ctx:
                c.transcribe({})
            self.assertEqual((ctx.exception.status, ctx.exception.message), (code, "bad"))
            self.assertEqual(len(self.opener.requests), 1)

    def test_missing_text_is_error(self):
        with self.assertRaises(OpenRouterError):
            self.client([{"nope": 1}] * 4).transcribe({})

    def test_requires_key(self):
        with self.assertRaises(OpenRouterError):
            OpenRouterClient("")


if __name__ == "__main__":
    unittest.main()
