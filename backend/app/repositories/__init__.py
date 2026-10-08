"""Concrete repositories, one per collection (section 18)."""
from __future__ import annotations

from app.db.mongo import C
from app.models.analysis import AnalysisJob, ReviewFinding, Specification
from app.models.approval import (ApprovalEvent, ApprovalManifest, Baseline,
                                 ChangeRequest)
from app.models.backlog import (ArtifactVersion, BacklogItem, Estimate,
                                RateCard)
from app.models.collaboration import (AuditEvent, Comment, EgressManifest,
                                      ExportJob, JobRecord, ReportDefinition,
                                      ShareGrant)
from app.models.identity import ProjectMember, User
from app.models.integration import (ExternalMapping, Integration, OutboxJob,
                                    SyncEvent)
from app.models.knowledge import (DependencyLink, EvidenceLink, GlossaryTerm,
                                  Question, Requirement, RequirementVersion)
from app.models.planning import (Allocation, Iteration, KanbanBoard, Leave,
                                 MetricSnapshot, Milestone, StatusEvent,
                                 Worklog)
from app.models.source import (ImpactReport, SourceChunk, SourceDocument,
                               SourceVersion, TranscriptSegment)
from app.models.testing import Testbook, TestCase, TestVersion
from app.repositories.base import Repo

users = Repo(C.USERS, User)
members = Repo(C.PROJECT_MEMBERS, ProjectMember)

source_documents = Repo(C.SOURCE_DOCUMENTS, SourceDocument)
source_versions = Repo(C.SOURCE_VERSIONS, SourceVersion)
source_chunks = Repo(C.SOURCE_CHUNKS, SourceChunk)
transcript_segments = Repo(C.TRANSCRIPT_SEGMENTS, TranscriptSegment)
impact_reports = Repo(C.IMPACT_REPORTS, ImpactReport)

glossary = Repo(C.GLOSSARY, GlossaryTerm)
requirements = Repo(C.REQUIREMENTS, Requirement)
requirement_versions = Repo(C.REQUIREMENT_VERSIONS, RequirementVersion)
questions = Repo(C.QUESTIONS, Question)
evidence_links = Repo(C.EVIDENCE_LINKS, EvidenceLink)
dependency_links = Repo(C.DEPENDENCY_LINKS, DependencyLink)

backlog_items = Repo(C.BACKLOG_ITEMS, BacklogItem)
artifact_versions = Repo(C.ARTIFACT_VERSIONS, ArtifactVersion)
estimates = Repo(C.ESTIMATES, Estimate)
rate_cards = Repo(C.RATE_CARDS, RateCard)
specifications = Repo(C.SPECIFICATIONS, Specification)

test_cases = Repo(C.TEST_CASES, TestCase)
test_versions = Repo(C.TEST_VERSIONS, TestVersion)
testbooks = Repo(C.TESTBOOKS, Testbook)

analysis_jobs = Repo(C.ANALYSIS_JOBS, AnalysisJob)
findings = Repo(C.REVIEW_FINDINGS, ReviewFinding)

approval_manifests = Repo(C.APPROVAL_MANIFESTS, ApprovalManifest)
approval_events = Repo(C.APPROVAL_EVENTS, ApprovalEvent)
baselines = Repo(C.BASELINES, Baseline)
change_requests = Repo(C.CHANGE_REQUESTS, ChangeRequest)

iterations = Repo(C.ITERATIONS, Iteration)
allocations = Repo(C.ALLOCATIONS, Allocation)
leaves = Repo("leaves", Leave)
worklogs = Repo(C.WORKLOGS, Worklog)
milestones = Repo("milestones", Milestone)
boards = Repo("kanbanBoards", KanbanBoard)
status_events = Repo(C.STATUS_EVENTS, StatusEvent)
metric_snapshots = Repo(C.METRIC_SNAPSHOTS, MetricSnapshot)

integrations = Repo(C.INTEGRATIONS, Integration)
external_mappings = Repo(C.EXTERNAL_MAPPINGS, ExternalMapping)
sync_events = Repo(C.SYNC_EVENTS, SyncEvent)
outbox = Repo(C.OUTBOX_JOBS, OutboxJob)

share_grants = Repo(C.SHARE_GRANTS, ShareGrant)
comments = Repo(C.COMMENTS, Comment)
report_definitions = Repo(C.REPORT_DEFINITIONS, ReportDefinition)
export_jobs = Repo(C.EXPORT_JOBS, ExportJob)
audit_events = Repo(C.AUDIT_EVENTS, AuditEvent)
egress_manifests = Repo(C.EGRESS_MANIFESTS, EgressManifest)
jobs = Repo(C.JOBS, JobRecord)

# ``projects`` is imported lazily to avoid a circular import with the project
# model module that references policy defaults.
from app.models.project import Project  # noqa: E402

projects = Repo(C.PROJECTS, Project)

__all__ = [
    "users", "members", "projects", "source_documents", "source_versions",
    "source_chunks", "transcript_segments", "impact_reports", "glossary",
    "requirements", "requirement_versions", "questions", "evidence_links",
    "dependency_links", "backlog_items", "artifact_versions", "estimates",
    "rate_cards", "specifications", "test_cases", "test_versions", "testbooks",
    "analysis_jobs", "findings", "approval_manifests", "approval_events",
    "baselines", "change_requests", "iterations", "allocations", "leaves",
    "worklogs", "milestones", "boards", "status_events", "metric_snapshots",
    "integrations", "external_mappings", "sync_events", "outbox",
    "share_grants", "comments", "report_definitions", "export_jobs",
    "audit_events", "egress_manifests", "jobs",
]
