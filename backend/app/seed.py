"""Seed a reference project so the deployment is usable immediately.

Creates accounts for each role, a bilingual project with Greek and English
evidence, a rate card, an iteration and a Kanban board, then runs the sequential
analyst workflow so the workspace has reviewable content.

Run with: ``python -m app.seed``
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from app.core.policy import Role
from app.core.security import hash_password
from app.core.utils import utcnow
from app.db.mongo import close, ensure_indexes
from app.models.backlog import RateCard
from app.models.common import Classification, DeliveryMethod, Language
from app.models.identity import ProjectMember, User
from app.models.planning import Iteration, KanbanBoard, KanbanColumn
from app.models.project import AIPolicy, Project, WorkingCalendar
from app.models.source import Authority, SourceCreate, SourceKind
from app.repositories import (boards, iterations, members, projects, rate_cards,
                              users)
from app.services import sources

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed")

PASSWORD = "Analyst!2026"

ACCOUNTS = [
    # The platform owner holds every permission in every project and is
    # deliberately given no membership record, so the seeded deployment proves
    # that ownership works without one.
    ("owner@company.local", "Platform Owner", [Role.SUPERUSER], []),
    ("admin@company.local", "System Administrator", [Role.SYSTEM_ADMIN], []),
    ("lead@company.local", "Lead Analyst", [], [Role.PROJECT_ADMIN, Role.LEAD_ANALYST]),
    ("ba@company.local", "Business Analyst", [], [Role.BUSINESS_ANALYST]),
    ("ta@company.local", "Technical Analyst", [], [Role.TECHNICAL_ANALYST]),
    ("qa@company.local", "QA Analyst", [], [Role.QA_ANALYST]),
    ("dm@company.local", "Delivery Manager", [], [Role.DELIVERY_MANAGER]),
    ("client@client.local", "Client Reviewer", [], [Role.CLIENT_REVIEWER]),
]

BRIEF_EN = """# Customer Portal — project brief

## Goal
The goal is to give customers a self service portal so that fewer support calls
are needed for routine requests.

## Scope
The portal must allow a customer to register with an email address and a
password. The system shall send a verification email before the account becomes
active. A customer must be able to reset a forgotten password.

An administrator must be able to deactivate a customer account. Only an
administrator shall be able to see other customers' invoices.

The portal must display the last 24 months of invoices. Invoice totals must
match the figures in the billing system. The system should allow a customer to
download an invoice as PDF.

Response time for the invoice list must be below 2 seconds for 95 percent of
requests.

Decision: the first release covers invoices only. Order tracking is out of scope.
Action: the billing team to confirm the invoice export format by the end of the
month.
Open question: it is unclear whether a customer with multiple companies sees a
combined invoice list or one list per company. TBD.
"""

NOTES_EL = """# Σημειώσεις συνάντησης — Πύλη Πελατών

Ο πελάτης πρέπει να μπορεί να συνδεθεί με τα στοιχεία που του δίνει ο
διαχειριστής. Το σύστημα θα πρέπει να κλειδώνει τον λογαριασμό μετά από πέντε
αποτυχημένες προσπάθειες.

Κανόνας: εφόσον ο λογαριασμός είναι ανενεργός, δεν επιτρέπεται η πρόσβαση στα
τιμολόγια.

Απόφαση: η πρώτη έκδοση υποστηρίζει ελληνικά και αγγλικά.
Ερώτηση: δεν είναι σαφές ποιος εγκρίνει την απενεργοποίηση ενός λογαριασμού.
Απαιτείται διευκρίνιση.

Ο χρόνος απόκρισης πρέπει να είναι αποδεκτός. Ασαφές τι σημαίνει αποδεκτός.
"""

SCHEDULE_CSV = """Milestone,Date,Owner,Notes
Discovery complete,2026-02-28,Lead Analyst,Evidence and questions closed
Design approved,2026-03-20,Client,Portal screens signed off
Release 1,2026-05-15,Delivery Manager,Invoices only
"""

TRANSCRIPT = """[00:12] Client: We need the invoice list to load quickly, it must be under two seconds.
[00:41] Analyst: And who is allowed to deactivate an account?
[00:48] Client: That is still open, we will confirm it next week.
[01:15] Client: The portal must support Greek and English for all customers.
[01:52] Analyst: Should a customer with two companies see one list or two?
[02:03] Client: Unclear for now, mark it as TBD.
"""


async def seed() -> None:
    await ensure_indexes()

    created: dict[str, User] = {}
    for email, name, global_roles, _ in ACCOUNTS:
        existing = await users.find_one({"email": email})
        if existing:
            created[email] = existing
            continue
        person = User(email=email, display_name=name,
                      password_hash=hash_password(PASSWORD),
                      global_roles=[str(r) for r in global_roles],
                      is_client=email.endswith("@client.local"),
                      locale=Language.EN)
        await users.insert(person)
        created[email] = person
        log.info("created user %s", email)

    if await projects.exists({"key": "PORTAL"}):
        log.info("reference project already exists, nothing to seed")
        await close()
        return

    lead = created["lead@company.local"]
    project = Project(
        key="PORTAL", name="Customer Portal", client_name="Northwind Retail",
        description=("Self service customer portal. Reference project seeded with "
                     "bilingual evidence."),
        languages=[Language.EN, Language.EL], output_language=Language.EN,
        delivery_method=DeliveryMethod.SCRUM,
        default_classification=Classification.CONFIDENTIAL,
        calendar=WorkingCalendar(timezone="Europe/Athens", hours_per_person_day=8.0,
                                 focus_factor=0.8),
        ai_policy=AIPolicy(cloud_enabled=False, local_only=True),
        currency="EUR", owner_id=lead.id,
        started_on=date.today(), target_end_on=date.today() + timedelta(days=120),
    )
    await projects.insert(project)
    log.info("created project %s", project.key)

    for email, _, _, project_roles in ACCOUNTS:
        if not project_roles:
            continue
        person = created[email]
        await members.insert(ProjectMember(
            project_id=project.id, user_id=person.id,
            roles=[str(r) for r in project_roles],
            delivery_role=("analysis" if "analyst" in email else
                           "delivery" if "dm@" in email else None),
            acceptance_authority=person.is_client,
            invited_by=lead.id))

    await rate_cards.insert(RateCard(
        project_id=project.id, name="Standard 2026", currency="EUR",
        effective_from=date(2026, 1, 1),
        rates={"analysis": "85.00", "engineering": "95.00", "qa": "75.00",
               "delivery": "110.00"},
        contingency_percent=10.0, created_by=lead.id))

    await boards.insert(KanbanBoard(project_id=project.id, columns=[
        KanbanColumn(key="backlog", name="Backlog", maps_to_status="not_started",
                     is_start=True),
        KanbanColumn(key="ready", name="Ready", maps_to_status="ready"),
        KanbanColumn(key="in_progress", name="In progress",
                     maps_to_status="in_progress", wip_limit=5),
        KanbanColumn(key="in_review", name="In review", maps_to_status="in_review",
                     wip_limit=3),
        KanbanColumn(key="done", name="Done", maps_to_status="done", is_done=True),
    ]))

    start = date.today() - timedelta(days=date.today().weekday())
    await iterations.insert(Iteration(
        project_id=project.id, name="Sprint 1", goal="Account and invoice foundations",
        start_date=start, end_date=start + timedelta(days=13), state="active",
        capacity_hours=240.0))

    evidence = [
        ("brief.md", BRIEF_EN.encode("utf-8"),
         SourceCreate(title="Customer Portal brief", kind=SourceKind.BRIEF,
                      authority=Authority.CONTRACTUAL)),
        ("meeting-notes-el.md", NOTES_EL.encode("utf-8"),
         SourceCreate(title="Σημειώσεις συνάντησης", kind=SourceKind.MEETING_NOTES,
                      authority=Authority.CONFIRMED)),
        ("schedule.csv", SCHEDULE_CSV.encode("utf-8"),
         SourceCreate(title="Delivery schedule", kind=SourceKind.SCHEDULE,
                      authority=Authority.WORKING)),
        ("kickoff-transcript.txt", TRANSCRIPT.encode("utf-8"),
         SourceCreate(title="Kick off recording transcript",
                      kind=SourceKind.MEETING_NOTES, authority=Authority.WORKING)),
    ]
    for filename, data, meta in evidence:
        await sources.upload(project.id, filename=filename, data=data, meta=meta,
                             actor_id=lead.id,
                             default_classification=project.default_classification)
        log.info("uploaded %s", filename)

    from app.ai import orchestrator
    from app.models.analysis import AnalysisRunRequest

    job = await orchestrator.start_job(project.id, AnalysisRunRequest(),
                                       actor_id=lead.id)
    log.info("running sequential analysis %s", job.id)
    result = await orchestrator.run_job(job.id)
    log.info("analysis finished: %s %s", result.status, result.created_counts)

    log.info("")
    log.info("Seed complete. Sign in with any of:")
    for email, name, global_roles, project_roles in ACCOUNTS:
        scope = ("owns every project" if Role.SUPERUSER in global_roles
                 else "deployment only, no project content" if global_roles
                 else ", ".join(str(role) for role in project_roles))
        log.info("  %-24s %-22s %s", email, name, scope)
    log.info("")
    log.info("Password for every seeded account: %s", PASSWORD)
    await close()


if __name__ == "__main__":
    asyncio.run(seed())
