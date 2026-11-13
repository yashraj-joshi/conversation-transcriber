"""In-memory stand-ins for the S3, SSM, and OpenRouter clients (no AWS SDK or network needed)."""

import io
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, page_size=1000):
        self.objects = {}
        self.metadata = {}
        self.page_size = page_size
        self.puts = []
        self.lock = threading.Lock()

    def put_object(self, Bucket, Key, Body, ContentType=None, Metadata=None):
        with self.lock:
            self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")
            self.metadata[Key] = Metadata or {}
            self.puts.append(Key)

    def get_object(self, Bucket, Key):
        with self.lock:
            if Key not in self.objects:
                raise FakeClientError("NoSuchKey")
            return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        if Delimiter:
            entries = []
            for k in keys:
                rest = k[len(Prefix):]
                if Delimiter in rest:
                    p = Prefix + rest.split(Delimiter, 1)[0] + Delimiter
                    if ("P", p) not in entries:
                        entries.append(("P", p))
                else:
                    entries.append(("K", k))
        else:
            entries = [("K", k) for k in keys]
        start = int(ContinuationToken or 0)
        page = entries[start:start + self.page_size]
        result = {
            "Contents": [{"Key": v, "Size": len(self.objects[v])} for t, v in page if t == "K"],
            "CommonPrefixes": [{"Prefix": v} for t, v in page if t == "P"],
            "IsTruncated": start + self.page_size < len(entries),
        }
        if result["IsTruncated"]:
            result["NextContinuationToken"] = str(start + self.page_size)
        return result

    def generate_presigned_post(self, Bucket, Key, Fields, Conditions, ExpiresIn):
        return {"url": f"https://{Bucket}.s3.amazonaws.com/",
                "fields": dict(Fields, key=Key, policy="p", **{"x-amz-signature": "s"}),
                "_conditions": Conditions, "_expires": ExpiresIn}


class FakeSSM:
    def __init__(self, values):
        self.values = dict(values)
        self.calls = []

    def get_parameter(self, Name, WithDecryption=False):
        self.calls.append((Name, WithDecryption))
        if Name not in self.values:
            raise FakeClientError("ParameterNotFound")
        return {"Parameter": {"Name": Name, "Value": self.values[Name]}}


class FakeTranscriber:
    """Fake OpenRouterClient: returns text per part, or raises configured errors."""

    def __init__(self, responder):
        self.responder = responder
        self.payloads = []
        self.lock = threading.Lock()

    def transcribe(self, payload):
        with self.lock:
            self.payloads.append(payload)
        return self.responder(payload)
