"""Test fixtures.

Database backed tests run against an in memory Mongo substitute so the suite
needs no infrastructure. Tests that depend on real transactional semantics are
marked and skipped unless a replica set is reachable.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from mongomock_motor import AsyncMongoMockClient



# Shared API fixtures, available to every suite (see tests/support.py).
from tests.support import (Actor, admin, analysed_project, client, lead,  # noqa: F401
                           outsider, project, project_with_evidence, reviewer)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Point the Mongo accessors at an in memory client for each test."""
    from app.db import mongo

    client = AsyncMongoMockClient()
    database = client["ai_analysis_team_test"]

    monkeypatch.setattr(mongo, "_client", client, raising=False)
    monkeypatch.setattr(mongo, "_db", database, raising=False)
    monkeypatch.setattr(mongo, "get_client", lambda: client)
    monkeypatch.setattr(mongo, "get_db", lambda: database)
    monkeypatch.setattr(mongo, "col", lambda name: database[name])

    async def no_transactions() -> bool:
        return False

    monkeypatch.setattr(mongo, "supports_transactions", no_transactions)
    yield database


@pytest.fixture
def today() -> date:
    return date.today()
