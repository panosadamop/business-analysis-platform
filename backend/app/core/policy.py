"""Role based authorization model (specification section 4).

Authorization is enforced server side on records, source chunks, search,
reports, downloads and job results. Client users never receive internal rate
cards, AI prompts, confidential evidence or internal comments unless the
project explicitly shared the exact version with them.
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    #: Platform owner. Holds every permission in every project without needing a
    #: membership record, and is entered in the audit trail as having acted
    #: through that standing. See ``SUPERUSER`` note below.
    SUPERUSER = "superuser"
    SYSTEM_ADMIN = "system_admin"
    PROJECT_ADMIN = "project_admin"
    LEAD_ANALYST = "lead_analyst"
    BUSINESS_ANALYST = "business_analyst"
    TECHNICAL_ANALYST = "technical_analyst"
    QA_ANALYST = "qa_analyst"
    UX_ANALYST = "ux_analyst"
    DATA_ANALYST = "data_analyst"
    DELIVERY_MANAGER = "delivery_manager"
    CONTRIBUTOR = "contributor"
    CLIENT_REVIEWER = "client_reviewer"
    INTERNAL_VIEWER = "internal_viewer"


class Permission(StrEnum):
    # project
    PROJECT_CREATE = "project.create"
    PROJECT_MANAGE = "project.manage"
    MEMBER_MANAGE = "member.manage"
    POLICY_MANAGE = "policy.manage"
    # evidence
    SOURCE_READ = "source.read"
    SOURCE_RAW_READ = "source.raw.read"
    SOURCE_UPLOAD = "source.upload"
    SOURCE_MANAGE = "source.manage"
    # analysis
    ANALYSIS_READ = "analysis.read"
    ANALYSIS_RUN = "analysis.run"
    # knowledge and backlog
    BACKLOG_READ = "backlog.read"
    BACKLOG_EDIT = "backlog.edit"
    SPEC_READ = "spec.read"
    SPEC_EDIT = "spec.edit"
    TEST_READ = "test.read"
    TEST_EDIT = "test.edit"
    # approval
    APPROVAL_PREVIEW = "approval.preview"
    APPROVAL_DECIDE = "approval.decide"
    APPROVAL_REVOKE = "approval.revoke"
    APPROVAL_WAIVE = "approval.waive"
    # plan and money
    BASELINE_MANAGE = "baseline.manage"
    CHANGE_DECIDE = "change.decide"
    ESTIMATE_EDIT = "estimate.edit"
    RATE_READ = "rate.read"
    RATE_MANAGE = "rate.manage"
    COST_READ = "cost.read"
    PLANNING_MANAGE = "planning.manage"
    WORKLOG_WRITE = "worklog.write"
    WORKLOG_APPROVE = "worklog.approve"
    METRICS_READ = "metrics.read"
    # outward facing
    INTEGRATION_MANAGE = "integration.manage"
    INTEGRATION_PUBLISH = "integration.publish"
    SHARE_MANAGE = "share.manage"
    CLIENT_COMMENT = "client.comment"
    CLIENT_ACCEPT = "client.accept"
    COMMENT_INTERNAL = "comment.internal"
    # reporting
    REPORT_READ = "report.read"
    REPORT_MANAGE = "report.manage"
    EXPORT_RUN = "export.run"
    # administration
    ADMIN_SYSTEM = "admin.system"
    AUDIT_READ = "audit.read"


_ANALYST_BASE = {
    Permission.SOURCE_READ, Permission.SOURCE_RAW_READ, Permission.SOURCE_UPLOAD,
    Permission.ANALYSIS_READ, Permission.ANALYSIS_RUN,
    Permission.BACKLOG_READ, Permission.SPEC_READ, Permission.TEST_READ,
    Permission.APPROVAL_PREVIEW, Permission.METRICS_READ,
    Permission.REPORT_READ, Permission.EXPORT_RUN, Permission.COMMENT_INTERNAL,
    Permission.WORKLOG_WRITE,
}

#: Section 4 separates infrastructure administration from content access: a
#: system administrator configures the deployment and still needs a project
#: entitlement to read project content. The superuser is the deliberate
#: exception the operator asked for — a single platform owner who owns
#: everything. It is a standing entitlement, not an absence of checks: every
#: permission is still evaluated, the role simply grants them all, and each
#: access it enables is recorded in the audit trail.
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.SUPERUSER: set(Permission),
    # The system administrator configures infrastructure. Content access still
    # requires a separate project entitlement, so no backlog permissions here.
    Role.SYSTEM_ADMIN: {
        Permission.ADMIN_SYSTEM, Permission.AUDIT_READ, Permission.PROJECT_CREATE,
        Permission.INTEGRATION_MANAGE,
    },
    Role.PROJECT_ADMIN: _ANALYST_BASE | {
        Permission.PROJECT_MANAGE, Permission.MEMBER_MANAGE, Permission.POLICY_MANAGE,
        Permission.SOURCE_MANAGE, Permission.BACKLOG_EDIT, Permission.SPEC_EDIT,
        Permission.TEST_EDIT, Permission.APPROVAL_DECIDE, Permission.APPROVAL_REVOKE,
        Permission.APPROVAL_WAIVE, Permission.BASELINE_MANAGE, Permission.CHANGE_DECIDE,
        Permission.ESTIMATE_EDIT, Permission.RATE_READ, Permission.RATE_MANAGE,
        Permission.COST_READ, Permission.PLANNING_MANAGE, Permission.WORKLOG_APPROVE,
        Permission.INTEGRATION_MANAGE, Permission.INTEGRATION_PUBLISH,
        Permission.SHARE_MANAGE, Permission.REPORT_MANAGE, Permission.AUDIT_READ,
    },
    Role.LEAD_ANALYST: _ANALYST_BASE | {
        Permission.BACKLOG_EDIT, Permission.SPEC_EDIT, Permission.TEST_EDIT,
        Permission.SOURCE_MANAGE, Permission.ESTIMATE_EDIT,
        Permission.APPROVAL_DECIDE, Permission.APPROVAL_REVOKE, Permission.APPROVAL_WAIVE,
        Permission.BASELINE_MANAGE, Permission.CHANGE_DECIDE, Permission.SHARE_MANAGE,
        Permission.REPORT_MANAGE, Permission.INTEGRATION_PUBLISH,
    },
    Role.BUSINESS_ANALYST: _ANALYST_BASE | {
        Permission.BACKLOG_EDIT, Permission.SPEC_EDIT, Permission.ESTIMATE_EDIT,
    },
    Role.TECHNICAL_ANALYST: _ANALYST_BASE | {
        Permission.BACKLOG_EDIT, Permission.SPEC_EDIT, Permission.ESTIMATE_EDIT,
    },
    Role.QA_ANALYST: _ANALYST_BASE | {
        Permission.TEST_EDIT, Permission.BACKLOG_EDIT,
    },
    Role.UX_ANALYST: _ANALYST_BASE | {
        Permission.BACKLOG_EDIT, Permission.SPEC_EDIT,
    },
    Role.DATA_ANALYST: _ANALYST_BASE | {
        Permission.BACKLOG_EDIT, Permission.SPEC_EDIT,
    },
    Role.DELIVERY_MANAGER: _ANALYST_BASE | {
        Permission.PLANNING_MANAGE, Permission.ESTIMATE_EDIT, Permission.RATE_READ,
        Permission.RATE_MANAGE, Permission.COST_READ, Permission.BASELINE_MANAGE,
        Permission.CHANGE_DECIDE, Permission.WORKLOG_APPROVE, Permission.REPORT_MANAGE,
        Permission.INTEGRATION_MANAGE, Permission.INTEGRATION_PUBLISH,
    },
    Role.CONTRIBUTOR: {
        Permission.SOURCE_READ, Permission.BACKLOG_READ, Permission.SPEC_READ,
        Permission.TEST_READ, Permission.ANALYSIS_READ, Permission.WORKLOG_WRITE,
        Permission.COMMENT_INTERNAL, Permission.METRICS_READ, Permission.REPORT_READ,
    },
    # Client reviewers never hold project wide read permissions. Everything they
    # see is resolved through an explicit, non revoked share grant.
    Role.CLIENT_REVIEWER: {
        Permission.CLIENT_COMMENT,
    },
    Role.INTERNAL_VIEWER: {
        Permission.SOURCE_READ, Permission.BACKLOG_READ, Permission.SPEC_READ,
        Permission.TEST_READ, Permission.ANALYSIS_READ, Permission.METRICS_READ,
        Permission.REPORT_READ,
    },
}

#: Fields that must never reach a client audience, including values derived
#: from them (REQ-REPORT-08, AT-11).
CLIENT_FORBIDDEN_FIELDS: frozenset[str] = frozenset({
    "estimatedCost", "actualCost", "forecastCost", "rate", "rateCardId",
    "effectiveHourlyRate", "budget", "margin", "internalNotes", "aiPrompt",
    "promptTemplateVersion", "modelId", "modelConfig", "tokenUsage", "costEur",
    "riskNotes", "internalComment", "rateBreakdown", "roleRates",
})

APPROVER_ROLES = {Role.PROJECT_ADMIN, Role.LEAD_ANALYST, Role.SYSTEM_ADMIN,
                  Role.SUPERUSER}


def permissions_for(roles: list[str] | set[str]) -> set[Permission]:
    granted: set[Permission] = set()
    for raw in roles:
        try:
            role = Role(raw)
        except ValueError:
            continue
        granted |= ROLE_PERMISSIONS.get(role, set())
    return granted


def is_client_role(roles: list[str] | set[str]) -> bool:
    return Role.CLIENT_REVIEWER in {str(r) for r in roles}


def is_superuser(roles: list[str] | set[str]) -> bool:
    """A superuser owns every project, with or without a membership record."""
    return Role.SUPERUSER in {str(r) for r in roles}


def is_platform_admin(roles: list[str] | set[str]) -> bool:
    """May administer the deployment: a system administrator or the superuser."""
    return bool({str(r) for r in roles} & {Role.SYSTEM_ADMIN, Role.SUPERUSER})
