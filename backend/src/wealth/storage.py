"""Where uploaded document files live: Amazon S3 on AWS, a local S3-compatible server (adobe/s3mock in docker compose) locally.

The same boto3 code runs in both places. On AWS the ECS task role's temporary credentials are used and the
bucket is private and encrypted (infra/app). Locally S3_ENDPOINT_URL points at the s3 container, with
its local-only keys from S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY.

Files are never served from the bucket directly: the API checks access, records the open, then streams the
bytes. So the bucket never needs a public URL.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config

from wealth.config import get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class S3Storage:
    def __init__(self, bucket: str, region: str, endpoint_url: str | None = None):
        self.bucket = bucket
        local = {}
        if endpoint_url:  # local S3: path-style URLs and its own (dummy) keys
            local = {
                "endpoint_url": endpoint_url,
                "aws_access_key_id": os.environ.get("S3_ACCESS_KEY_ID"),
                "aws_secret_access_key": os.environ.get("S3_SECRET_ACCESS_KEY"),
                "config": Config(s3={"addressing_style": "path"}),
            }
        self.client = boto3.client("s3", region_name=region, **local)
        if endpoint_url:
            self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Local only: create the bucket on first use. On AWS Terraform creates it."""
        existing = {b["Name"] for b in self.client.list_buckets().get("Buckets", [])}
        if self.bucket not in existing:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()


class MemoryStorage:
    """For tests."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail = False

    def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.fail:
            raise RuntimeError("storage is down")
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> bytes:
        return self.objects[key][0]


@lru_cache(maxsize=1)
def _s3() -> S3Storage | None:
    s = get_settings()
    if not s.documents_bucket:
        return None
    return S3Storage(s.documents_bucket, s.s3_region, s.s3_endpoint_url)


def get_storage() -> Storage | None:
    """None when uploads aren't configured (no DOCUMENTS_BUCKET). Tests override this dependency."""
    return _s3()
