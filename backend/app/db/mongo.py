"""MongoDB connection, collection registry and index bootstrap (section 18)."""
from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorDatabase)
from pymongo import ASCENDING, DESCENDING, IndexModel, TEXT

from app.core.config import settings

log = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


class C:
    """Collection names. Bounded aggregates, referenced collections."""

    USERS = "users"
    PROJECTS = "projects"
    PROJECT_MEMBERS = "projectMembers"
    SOURCE_DOCUMENTS = "sourceDocuments"
    SOURCE_VERSIONS = "sourceVersions"
    SOURCE_CHUNKS = "sourceChunks"
    TRANSCRIPT_SEGMENTS = "transcriptSegments"
    GLOSSARY = "glossaryTerms"
    REQUIREMENTS = "requirements"
    REQUIREMENT_VERSIONS = "requirementVersions"
    QUESTIONS = "questions"
    BACKLOG_ITEMS = "backlogItems"
    ARTIFACT_VERSIONS = "artifactVersions"
    EVIDENCE_LINKS = "evidenceLinks"
    DEPENDENCY_LINKS = "dependencyLinks"
    ESTIMATES = "estimates"
    RATE_CARDS = "rateCards"
    SPECIFICATIONS = "specifications"
    TEST_CASES = "testCases"
    TEST_VERSIONS = "testVersions"
    TESTBOOKS = "testbooks"
    ANALYSIS_JOBS = "analysisJobs"
    REVIEW_FINDINGS = "reviewFindings"
    APPROVAL_EVENTS = "approvalEvents"
    APPROVAL_MANIFESTS = "approvalManifests"
    BASELINES = "baselines"
    CHANGE_REQUESTS = "changeRequests"
    ITERATIONS = "iterations"
    ALLOCATIONS = "allocations"
    WORKLOGS = "worklogs"
    STATUS_EVENTS = "statusEvents"
    METRIC_SNAPSHOTS = "metricSnapshots"
    INTEGRATIONS = "integrations"
    EXTERNAL_MAPPINGS = "externalMappings"
    SYNC_EVENTS = "syncEvents"
    OUTBOX_JOBS = "outboxJobs"
    SHARE_GRANTS = "shareGrants"
    COMMENTS = "comments"
    REPORT_DEFINITIONS = "reportDefinitions"
    EXPORT_JOBS = "exportJobs"
    AUDIT_EVENTS = "auditEvents"
    EGRESS_MANIFESTS = "egressManifests"
    CALIBRATION_VERSIONS = "calibrationVersions"
    JOBS = "jobs"
    IMPACT_REPORTS = "impactReports"


INDEXES: dict[str, list[IndexModel]] = {
    C.USERS: [IndexModel([("email", ASCENDING)], unique=True)],
    C.PROJECTS: [IndexModel([("key", ASCENDING)], unique=True)],
    C.PROJECT_MEMBERS: [
        IndexModel([("projectId", ASCENDING), ("userId", ASCENDING)], unique=True),
        IndexModel([("userId", ASCENDING)]),
    ],
    C.SOURCE_DOCUMENTS: [
        IndexModel([("projectId", ASCENDING), ("createdAt", DESCENDING)]),
        IndexModel([("projectId", ASCENDING), ("contentHash", ASCENDING)]),
    ],
    C.SOURCE_VERSIONS: [IndexModel([("documentId", ASCENDING), ("version", DESCENDING)])],
    C.SOURCE_CHUNKS: [
        IndexModel([("projectId", ASCENDING), ("sourceVersionId", ASCENDING)]),
        IndexModel([("projectId", ASCENDING), ("text", TEXT)], default_language="none"),
    ],
    C.TRANSCRIPT_SEGMENTS: [IndexModel([("sourceVersionId", ASCENDING), ("startMs", ASCENDING)])],
    C.REQUIREMENTS: [
        IndexModel([("projectId", ASCENDING), ("stableId", ASCENDING)], unique=True),
    ],
    C.QUESTIONS: [IndexModel([("projectId", ASCENDING), ("severity", ASCENDING)])],
    C.BACKLOG_ITEMS: [
        IndexModel([("projectId", ASCENDING), ("stableId", ASCENDING)], unique=True),
        IndexModel([("projectId", ASCENDING), ("parentId", ASCENDING)]),
        IndexModel([("projectId", ASCENDING), ("type", ASCENDING)]),
    ],
    C.ARTIFACT_VERSIONS: [
        IndexModel([("itemId", ASCENDING), ("version", DESCENDING)]),
        IndexModel([("projectId", ASCENDING), ("state", ASCENDING)]),
    ],
    C.EVIDENCE_LINKS: [
        IndexModel([("projectId", ASCENDING), ("targetId", ASCENDING)]),
        IndexModel([("projectId", ASCENDING), ("sourceVersionId", ASCENDING)]),
    ],
    C.DEPENDENCY_LINKS: [IndexModel([("projectId", ASCENDING), ("fromId", ASCENDING)])],
    C.ESTIMATES: [IndexModel([("projectId", ASCENDING), ("itemId", ASCENDING),
                              ("createdAt", DESCENDING)])],
    C.RATE_CARDS: [IndexModel([("projectId", ASCENDING), ("effectiveFrom", DESCENDING)])],
    C.TEST_CASES: [
        IndexModel([("projectId", ASCENDING), ("stableId", ASCENDING)], unique=True),
        IndexModel([("projectId", ASCENDING), ("storyId", ASCENDING)]),
    ],
    C.ANALYSIS_JOBS: [IndexModel([("projectId", ASCENDING), ("createdAt", DESCENDING)])],
    C.REVIEW_FINDINGS: [IndexModel([("projectId", ASCENDING), ("jobId", ASCENDING)])],
    C.APPROVAL_EVENTS: [IndexModel([("projectId", ASCENDING), ("decidedAt", DESCENDING)])],
    C.BASELINES: [IndexModel([("projectId", ASCENDING), ("createdAt", DESCENDING)])],
    C.WORKLOGS: [
        IndexModel([("projectId", ASCENDING), ("workDate", DESCENDING)]),
        IndexModel([("origin", ASCENDING), ("externalId", ASCENDING)], unique=True,
                   partialFilterExpression={"externalId": {"$type": "string"}}),
    ],
    C.EXTERNAL_MAPPINGS: [
        IndexModel([("integrationId", ASCENDING), ("internalId", ASCENDING)], unique=True),
        IndexModel([("integrationId", ASCENDING), ("externalId", ASCENDING)], unique=True),
    ],
    C.OUTBOX_JOBS: [
        IndexModel([("status", ASCENDING), ("availableAt", ASCENDING)]),
        IndexModel([("idempotencyKey", ASCENDING)], unique=True,
                   partialFilterExpression={"idempotencyKey": {"$type": "string"}}),
    ],
    C.SYNC_EVENTS: [IndexModel([("integrationId", ASCENDING), ("eventId", ASCENDING)],
                               unique=True)],
    C.JOBS: [
        IndexModel([("status", ASCENDING), ("availableAt", ASCENDING)]),
        IndexModel([("projectId", ASCENDING), ("createdAt", DESCENDING)]),
        IndexModel([("idempotencyKey", ASCENDING)], unique=True,
                   partialFilterExpression={"idempotencyKey": {"$type": "string"}}),
    ],
    C.SHARE_GRANTS: [IndexModel([("projectId", ASCENDING), ("audienceUserId", ASCENDING)])],
    C.COMMENTS: [IndexModel([("projectId", ASCENDING), ("targetId", ASCENDING)])],
    C.AUDIT_EVENTS: [IndexModel([("projectId", ASCENDING), ("at", DESCENDING)])],
    C.EGRESS_MANIFESTS: [IndexModel([("projectId", ASCENDING), ("at", DESCENDING)])],
    C.METRIC_SNAPSHOTS: [IndexModel([("projectId", ASCENDING), ("asOf", DESCENDING)])],
    C.STATUS_EVENTS: [IndexModel([("projectId", ASCENDING), ("at", DESCENDING)])],
    C.EXPORT_JOBS: [IndexModel([("projectId", ASCENDING), ("createdAt", DESCENDING)])],
}


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri, uuidRepresentation="standard",
                                     tz_aware=True)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        _db = get_client()[settings.mongo_db]
    return _db


def col(name: str) -> AsyncIOMotorCollection:
    return get_db()[name]


async def ensure_indexes() -> None:
    db = get_db()
    for name, models in INDEXES.items():
        try:
            await db[name].create_indexes(models)
        except Exception as exc:  # pragma: no cover - index drift is non fatal
            log.warning("index creation failed for %s: %s", name, exc)


async def supports_transactions() -> bool:
    """Replica set deployments allow multi document transactions (section 17.2)."""
    try:
        info: dict[str, Any] = await get_client().admin.command("hello")
        return bool(info.get("setName")) or info.get("msg") == "isdbgrid"
    except Exception:
        return False


async def close() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
