"""Identifier, time and money helpers.

Section 18 requires UTC timestamps stored separately from user/project timezone
and decimal safe money representation with an explicit currency.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex
    return f"{prefix}-{raw}" if prefix else raw


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalise a stored timestamp to an aware UTC value.

    Drivers and deployments differ in whether they return timezone aware
    datetimes, and comparing a naive one with an aware one raises. Everything
    that compares a stored timestamp goes through here first.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-") or "item"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_hash(payload: Any) -> str:
    """Deterministic hash used for sync payload comparison (section 14.2)."""
    import json

    return sha256_text(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False))


def money(amount: Decimal | float | int | str) -> Decimal:
    """Round a monetary amount to 2 decimals without float drift."""
    return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def hours(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_sum(values: Iterable[Decimal | float | int]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += Decimal(str(value))
    return total


def chunked(items: list[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]
