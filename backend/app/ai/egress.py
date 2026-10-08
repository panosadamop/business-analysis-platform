"""Outbound policy gate and payload minimisation (section 8.3, NFR-02, AT-07).

Cloud AI cannot analyse company content without receiving some of it. Keeping
originals locally is not the same as zero disclosure. This module therefore does
three separate things and never conflates them:

1. decides whether a payload may leave company infrastructure at all,
2. reduces what is disclosed (sanitisation reduces, it does not anonymise),
3. records an internal manifest of the disclosure categories.

A cloud or provider failure never causes a local only project to fall back to
cloud; the gate is the only path outward and it is default deny.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.core.config import settings
from app.core.utils import sha256_text, utcnow
from app.models.collaboration import EgressManifest
from app.models.common import Classification
from app.models.project import Project
from app.repositories import egress_manifests

#: Order matters: the first matching rule wins.
REDACTION_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+"), "[email]"),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "[iban]"),
    ("credential", re.compile(r"(?i)\b(api[_\- ]?key|secret|password|token|bearer)\b\s*[:=]\s*\S+"),
     "[credential]"),
    ("phone", re.compile(r"(?<!\d)(\+?\d[\d\s\-]{7,}\d)(?!\d)"), "[phone]"),
    ("vat", re.compile(r"(?i)\b(?:ΑΦΜ|AFM|VAT)\s*[:#]?\s*\d{6,12}\b"), "[tax-id]"),
    ("url_with_auth", re.compile(r"https?://[^\s/]+:[^\s@]+@\S+"), "[url]"),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
]

DISCLOSURE_CATEGORIES = {
    "requirement_text": "Requirement and backlog wording",
    "evidence_excerpt": "Excerpts of uploaded evidence",
    "project_metadata": "Project name, languages and delivery method",
    "glossary": "Project glossary terms",
    "acceptance_criteria": "Acceptance criteria wording",
}


class EgressDenied(Exception):
    """Raised when policy refuses to release a payload."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class PreparedPayload:
    text: str
    categories: list[str] = field(default_factory=list)
    redactions: dict[str, int] = field(default_factory=dict)
    chunk_count: int = 0
    char_count: int = 0
    payload_hash: str = ""


def sanitize(text: str) -> tuple[str, dict[str, int]]:
    """Remove identities, secrets and obvious sensitive data.

    This reduces disclosure. It is not a guarantee of anonymisation and is
    never presented as one.
    """
    counts: dict[str, int] = {}
    cleaned = text
    for name, pattern, replacement in REDACTION_RULES:
        cleaned, hits = pattern.subn(replacement, cleaned)
        if hits:
            counts[name] = counts.get(name, 0) + hits
    return cleaned, counts


def allowed_classifications(project: Project, *, target: str) -> set[str]:
    """Which classifications a given target (local or cloud) may process."""
    if target == "local":
        return {str(Classification.RESTRICTED), str(Classification.CONFIDENTIAL),
                str(Classification.SHAREABLE)}
    policy = project.ai_policy
    if policy.local_only or not policy.cloud_enabled or not settings.cloud_enabled_globally:
        return set()
    allowed = {str(Classification.SHAREABLE)}
    if policy.max_cloud_classification == Classification.CONFIDENTIAL:
        allowed.add(str(Classification.CONFIDENTIAL))
    return allowed


def check(project: Project, *, target: str, classifications: Iterable[str]) -> None:
    """Default deny. Raises :class:`EgressDenied` with a specific reason."""
    if target == "local":
        return
    policy = project.ai_policy
    if not settings.cloud_enabled_globally:
        raise EgressDenied("Cloud processing is disabled for this deployment")
    if policy.local_only:
        raise EgressDenied("The project is configured as local only")
    if not policy.cloud_enabled:
        raise EgressDenied("Cloud processing is not enabled for this project")
    permitted = allowed_classifications(project, target="cloud")
    blocked = sorted({c for c in classifications if c not in permitted})
    if blocked:
        raise EgressDenied(
            f"Content classified as {', '.join(blocked)} may not leave company "
            "infrastructure under this project's policy")


async def prepare(project: Project, *, target: str, role: str, model_id: str,
                  chunks: list[tuple[str, str]], categories: list[str],
                  actor_id: str | None = None) -> PreparedPayload:
    """Validate, minimise and record an outbound payload.

    ``chunks`` is a list of ``(classification, text)`` pairs.
    """
    classifications = [c for c, _ in chunks]
    try:
        check(project, target=target, classifications=classifications)
    except EgressDenied as denied:
        await egress_manifests.insert(EgressManifest(
            project_id=project.id, at=utcnow(), allowed=False,
            provider=target, model_id=model_id, role=role,
            classification=",".join(sorted(set(classifications))),
            disclosure_categories=categories, blocked_reason=denied.reason,
            actor_id=actor_id,
        ))
        raise

    permitted = allowed_classifications(project, target=target)
    kept = [text for classification, text in chunks if classification in permitted]
    joined = "\n\n".join(kept)
    redactions: dict[str, int] = {}
    if target != "local" and project.ai_policy.sanitize_payloads:
        joined, redactions = sanitize(joined)

    payload = PreparedPayload(
        text=joined, categories=categories, redactions=redactions,
        chunk_count=len(kept), char_count=len(joined),
        payload_hash=sha256_text(joined),
    )
    if target != "local":
        # Categories and counts only. Sensitive payloads never enter logs.
        await egress_manifests.insert(EgressManifest(
            project_id=project.id, at=utcnow(), allowed=True, provider=target,
            model_id=model_id, role=role,
            classification=",".join(sorted(set(classifications))),
            disclosure_categories=categories, redactions=redactions,
            chunk_count=payload.chunk_count, char_count=payload.char_count,
            payload_hash=payload.payload_hash, actor_id=actor_id,
        ))
    return payload


def strip_injected_instructions(text: str) -> str:
    """Imported content is untrusted data (section 8.2).

    Embedded instructions never override system policy, grant tool access or
    initiate external writes, so recognised instruction framing is neutralised
    before the text is placed into a role prompt.
    """
    patterns = [
        r"(?i)ignore (all )?(previous|prior|above) instructions",
        r"(?i)disregard (the )?(system|previous) (prompt|instructions)",
        r"(?i)you are now (an?|the)\b",
        r"(?i)\bsystem\s*:\s*",
        r"(?i)<\s*/?\s*(system|assistant|tool)\s*>",
        r"(?i)\bexecute\b.{0,20}\b(command|shell|sql)\b",
        r"(?i)\b(curl|wget|fetch)\s+https?://",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "[instruction-like text removed]", cleaned)
    return cleaned
