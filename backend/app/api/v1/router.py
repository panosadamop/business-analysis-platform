"""Versioned API router (section 17.3)."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (admin, analysis, approvals, auth, backlog, integrations,
                        knowledge, planning, projects, reports, sharing, sources,
                        testing)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(sources.router)
api_router.include_router(knowledge.router)
api_router.include_router(analysis.router)
api_router.include_router(backlog.router)
api_router.include_router(approvals.router)
api_router.include_router(testing.router)
api_router.include_router(planning.router)
api_router.include_router(integrations.router)
api_router.include_router(integrations.webhooks)
api_router.include_router(sharing.router)
api_router.include_router(sharing.client)
api_router.include_router(reports.router)
api_router.include_router(admin.router)
api_router.include_router(admin.project_admin)
