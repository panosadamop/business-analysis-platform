"""Fixtures for service level (unit) tests.

These build domain objects directly, without going through the API, so a
service can be exercised in isolation. The API and acceptance suites use the
HTTP fixtures in ``tests/support.py`` instead.
"""
from __future__ import annotations

import pytest

from app.core.security import hash_password
from app.models.common import Classification, Language
from app.models.identity import ProjectMember, User
from app.models.project import AIPolicy, Project, WorkingCalendar


@pytest.fixture
async def lead_user() -> User:
    from app.repositories import users

    user = User(email="lead@test.local", display_name="Lead Analyst",
                password_hash=hash_password("x"), locale=Language.EN)
    await users.insert(user)
    return user


@pytest.fixture
async def project(lead_user: User) -> Project:
    from app.repositories import members, projects

    item = Project(
        key="TEST", name="Test project", languages=[Language.EN, Language.EL],
        default_classification=Classification.CONFIDENTIAL,
        calendar=WorkingCalendar(hours_per_person_day=8.0, focus_factor=1.0),
        ai_policy=AIPolicy(local_only=True, cloud_enabled=False),
        owner_id=lead_user.id,
    )
    await projects.insert(item)
    await members.insert(ProjectMember(project_id=item.id, user_id=lead_user.id,
                                       roles=["project_admin", "lead_analyst"]))
    return item


