"""Encrypted secret storage for connector credentials (section 14.2).

Credentials remain encrypted on company infrastructure, are referenced by id
everywhere else in the system, and never enter an AI context or a log line.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import NotFound
from app.core.utils import new_id, utcnow
from app.db.mongo import col

COLLECTION = "secrets"


def _key() -> bytes:
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_key())


async def store(payload: dict[str, Any], *, project_id: str | None = None,
                secret_ref: str | None = None) -> str:
    ref = secret_ref or f"secret-{new_id()}"
    token = _fernet().encrypt(json.dumps(payload).encode()).decode()
    await col(COLLECTION).update_one(
        {"_id": ref},
        {"$set": {"projectId": project_id, "payload": token, "updatedAt": utcnow()},
         "$setOnInsert": {"createdAt": utcnow()}},
        upsert=True)
    return ref


async def read(secret_ref: str) -> dict[str, Any]:
    doc = await col(COLLECTION).find_one({"_id": secret_ref})
    if not doc:
        raise NotFound("Secret not found")
    try:
        return json.loads(_fernet().decrypt(doc["payload"].encode()).decode())
    except InvalidToken as exc:
        raise NotFound("Stored secret cannot be decrypted with the current key") from exc


async def delete(secret_ref: str) -> None:
    await col(COLLECTION).delete_one({"_id": secret_ref})
