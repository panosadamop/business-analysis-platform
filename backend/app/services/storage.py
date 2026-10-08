"""Company controlled object storage for originals, recordings and exports.

S3 compatible storage (MinIO in the reference deployment) with a local volume
fallback. Neither path ever leaves company infrastructure (section 17.1).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings

log = logging.getLogger(__name__)

_client = None
_use_s3: bool | None = None


def _fallback_path(key: str) -> Path:
    path = Path(settings.storage_fallback_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _client_or_none():
    global _client, _use_s3
    if _use_s3 is False:
        return None
    if _client is not None:
        return _client
    try:
        import boto3
        from botocore.client import Config

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", connect_timeout=3, retries={"max_attempts": 2}),
        )
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except Exception:
            client.create_bucket(Bucket=settings.s3_bucket)
        _client, _use_s3 = client, True
        return client
    except Exception as exc:
        log.warning("object storage unavailable, using local company volume: %s", exc)
        _use_s3 = False
        return None


def put_bytes(key: str, data: bytes, content_type: str | None = None) -> str:
    client = _client_or_none()
    if client is not None:
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data,
                          ContentType=content_type or "application/octet-stream")
        return key
    _fallback_path(key).write_bytes(data)
    return key


def put_stream(key: str, stream: BinaryIO, content_type: str | None = None) -> int:
    data = stream.read()
    put_bytes(key, data, content_type)
    return len(data)


def get_bytes(key: str) -> bytes:
    client = _client_or_none()
    if client is not None:
        return client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    path = _fallback_path(key)
    if not path.exists():
        raise FileNotFoundError(key)
    return path.read_bytes()


def exists(key: str) -> bool:
    client = _client_or_none()
    if client is not None:
        try:
            client.head_object(Bucket=settings.s3_bucket, Key=key)
            return True
        except Exception:
            return False
    return _fallback_path(key).exists()


def delete(key: str) -> None:
    client = _client_or_none()
    if client is not None:
        client.delete_object(Bucket=settings.s3_bucket, Key=key)
        return
    path = _fallback_path(key)
    if path.exists():
        os.remove(path)


def presigned_url(key: str, expires_seconds: int = 900) -> str | None:
    """Expiring download link (REQ-REPORT-08). ``None`` when streaming locally."""
    client = _client_or_none()
    if client is None:
        return None
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
    except Exception:
        return None
