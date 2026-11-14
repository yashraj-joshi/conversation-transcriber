"""In-memory stand-ins for the S3, SSM, and OpenRouter clients (no AWS SDK or network needed)."""

import io
import os
import sys
import threading
from datetime import datetime, timezone

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
        self.modified = {}
        self.lock = threading.Lock()
        self.clock = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)

    def put_object(self, Bucket, Key, Body, ContentType=None, Metadata=None):
        with self.lock:
            self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")
            self.metadata[Key] = Metadata or {}
            self.modified[Key] = self.clock
            self.puts.append(Key)

    def get_object(self, Bucket, Key, Range=None):
        with self.lock:
            if Key not in self.objects:
                raise FakeClientError("NoSuchKey")
            data = self.objects[Key]
            if Range:
                lo, hi = Range.split("=")[1].split("-")
                data = data[int(lo):int(hi) + 1]
            return {"Body": io.BytesIO(data), "Metadata": dict(self.metadata.get(Key, {}))}

    def head_object(self, Bucket, Key):
        with self.lock:
            if Key not in self.objects:
                raise FakeClientError("404")
            return {"Metadata": dict(self.metadata.get(Key, {})), "ContentLength": len(self.objects[Key])}

    def copy_object(self, Bucket, Key, CopySource, MetadataDirective="COPY"):
        src = CopySource["Key"]
        with self.lock:
            if src not in self.objects:
                raise FakeClientError("NoSuchKey")
            self.objects[Key] = self.objects[src]
            self.metadata[Key] = dict(self.metadata.get(src, {}))
            self.modified[Key] = self.clock

    def delete_object(self, Bucket, Key):
        with self.lock:
            self.objects.pop(Key, None)
            self.metadata.pop(Key, None)

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.delete_object(Bucket, o["Key"])

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
            "Contents": [{"Key": v, "Size": len(self.objects[v]), "LastModified": self.modified.get(v, self.clock)}
                         for t, v in page if t == "K"],
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
