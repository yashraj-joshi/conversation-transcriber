"""Minimal OpenRouter speech-to-text client (stdlib only).

POST https://openrouter.ai/api/v1/audio/transcriptions with a JSON body; see plan 002 R1/R7.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import core

DEFAULT_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
BACKOFF_SECONDS = (2, 4, 8)
MAX_RETRY_AFTER = 20


class OpenRouterError(Exception):
    def __init__(self, status, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    @property
    def retryable(self) -> bool:
        return core.is_retryable(self.status)


def _provider_message(raw: bytes) -> str:
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return raw.decode("utf-8", "replace")[:300]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "")
    return str(err or "")


class OpenRouterClient:
    def __init__(self, api_key: str, url: str = DEFAULT_URL, opener=None, sleep=time.sleep,
                 timeout: float = 120.0, max_attempts: int = 4, app_title: str | None = None):
        if not api_key:
            raise OpenRouterError(401, "OpenRouter API key is not configured")
        self._api_key = api_key
        self._url = url
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._app_title = app_title

    def _request(self, payload: dict):
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._app_title:
            headers["X-Title"] = self._app_title
        return urllib.request.Request(
            self._url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )

    def transcribe(self, payload: dict) -> dict:
        """Send one transcription request, retrying transient failures. Returns the parsed JSON."""
        last_error = None
        for attempt in range(self._max_attempts):
            retry_after = None
            try:
                with self._open(self._request(payload), timeout=self._timeout) as resp:
                    body = resp.read()
                data = json.loads(body.decode("utf-8"))
                if not isinstance(data, dict) or "text" not in data:
                    raise OpenRouterError(502, "response has no 'text' field")
                return data
            except urllib.error.HTTPError as exc:
                raw = exc.read() if hasattr(exc, "read") else b""
                last_error = OpenRouterError(exc.code, _provider_message(raw or b""))
                header = exc.headers.get("Retry-After") if exc.headers else None
                if header and header.strip().isdigit():
                    retry_after = min(int(header.strip()), MAX_RETRY_AFTER)
            except OpenRouterError as exc:
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = OpenRouterError(None, str(getattr(exc, "reason", exc)))
            if not last_error.retryable or attempt == self._max_attempts - 1:
                break
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            self._sleep(retry_after if retry_after is not None else delay)
        raise last_error
