# AI Analysis Team

An internal, company hosted application that operates as a coordinated AI team of
Business Analysts, Technical Analysts and QA Analysts, with optional UX and Data
Analysts chosen per project. It turns project evidence
into reviewable requirements, delivery backlogs, estimates, specifications and
testbooks, supports controlled client collaboration, and keeps traceability from
evidence to external delivery item.

Implemented from `AI_Analysis_Team_Software_Specification.md` (version 1.0).

**Every generated artifact is a draft that requires human approval. Approving a
parent approves its current descendant versions through a recorded, version bound
cascade.**

---

## Stack

| Layer | Technology |
|---|---|
| Web application | React 18, TypeScript, Tailwind CSS, Vite, TanStack Query |
| API | Python 3.12, FastAPI, Pydantic v2 |
| AI workers and orchestration | Python (same image, separate process) |
| Primary database | MongoDB 7 (replica set, for transactional approval commits) |
| Object storage | Company hosted S3 compatible storage (MinIO), with a local volume fallback |
| Queue | Durable MongoDB backed job queue with idempotency keys and backoff |
| Deployment | Docker Compose, non root containers, health checks, resource limits |

The specification proposed a TypeScript backend with Python AI workers. This
implementation uses Python for the whole backend as requested, keeping the API
and the AI workers in one codebase and one image, started as two processes.

---

## Quick start

### With Docker (company hosted deployment)

```bash
cp .env.example .env          # then edit APP_JWT_SECRET and APP_S3_SECRET_KEY
docker compose up -d --build
docker compose run --rm seed  # optional: seed the reference project
```

Open <http://localhost:8080>. The API is proxied through the web tier at
`/api/v1`; the database, object store and inference ports are bound to localhost
only and are never published.

### Locally, without Docker

```bash
# MongoDB as a replica set (transactions are used when available)
docker run -d --name ait-mongo -p 27017:27017 mongo:7 --replSet rs0 --bind_ip_all
docker exec ait-mongo mongosh --quiet --eval \
  'rs.initiate({_id:"rs0",members:[{_id:0,host:"localhost:27017"}]})'

# Backend
cd backend
python -m venv .venv && ./.venv/Scripts/pip install -r requirements-dev.txt
APP_MONGO_URI="mongodb://localhost:27017/?replicaSet=rs0" ./.venv/Scripts/python -m app.seed
APP_MONGO_URI="mongodb://localhost:27017/?replicaSet=rs0" ./.venv/Scripts/python -m uvicorn app.main:app --reload
# second terminal: the background worker
APP_MONGO_URI="mongodb://localhost:27017/?replicaSet=rs0" ./.venv/Scripts/python -m app.workers.worker

# Frontend
cd frontend && npm install && npm run dev      # http://localhost:5173
```

API documentation: <http://localhost:8000/api/docs>.

### Seeded accounts

All use the password `Analyst!2026`:

| Account | Role |
|---|---|
| `owner@company.local` | **Platform owner** — every permission in every project, no membership needed |
| `admin@company.local` | System administrator (deployment only; no project content) |
| `lead@company.local` | Project administrator and lead analyst (approver) |
| `ba@company.local` / `ta@company.local` / `qa@company.local` | Analysts |
| `dm@company.local` | Delivery manager |
| `client@client.local` | Client reviewer (sees only shared versions) |

The seed creates the `PORTAL` project with Greek and English evidence and runs
the full BA → Technical Analyst → QA workflow, producing requirements,
questions, a backlog hierarchy, specifications and test cases.

Each project chooses its analysts under **Project setup → Analysts**. A run
always executes them in the order BA → UX → Data → Technical → QA. The business,
technical and QA analysts are on by default; the UX analyst (personas, journeys,
screen states, accessibility requirements) and the data analyst (data quality
rules, metrics, retention, migration) are opt in, so enabling them never changes
an existing project's runs.

The platform owner is a deliberate exception to the specification's separation of
infrastructure administration from content access. It is a standing entitlement
rather than a bypass: every permission check still runs, reaching a project
without a membership record is written to the audit trail, and the deployment
refuses to remove the last active owner. See `docs/decisions.md` (D-19) for the
reasoning and the cost.

---

## What runs without any model configured

The AI gateway routes to a **deterministic local analyst** when no inference
service is configured. It is a transparent, rule based baseline: it extracts
requirement candidates from obligation wording, raises questions for ambiguity
markers, proposes a backlog hierarchy with citations to real evidence locators,
derives data entities and API operations, and generates descriptive tests with
Gherkin. Same evidence in, same analysis out.

To use a real model:

* **Local** — point `APP_LOCAL_INFERENCE_URL` at a company hosted OpenAI
  compatible endpoint (`docker compose --profile local-ai up -d` starts one).
* **Cloud** — set `APP_CLOUD_ENABLED_GLOBALLY=true`, `APP_CLOUD_PROVIDER` and
  `APP_CLOUD_API_KEY`, then enable cloud **per project**. Cloud is default deny
  at both levels, and a project may be stricter than the deployment, never looser.

---

## Authoring entries by hand

Everything the analyst workflow generates can also be written manually, with the
same rules: a hand written entry starts as a draft, its Gherkin is validated
before it is saved, and it needs the same editing permission.

| Entry | Where |
|---|---|
| Requirement, question, glossary term | Analysis workspace |
| Backlog item, evidence link | Backlog workspace |
| Specification (narrative, Mermaid diagram, structured JSON) | Specification workspace |
| Test case with Gherkin | Testbook workspace |
| Sprint, milestone, allocation, time entry | Planning workspace |
| Rate card, member | Project setup |

The requirement form asks how the statement is supported — evidence backed,
analyst assumption or client decision — so provenance is a choice, never an
inference.

## Charting a report

The report builder plots what it previews: choose a grouping column, a measure
and an aggregation (sum, count, average, minimum, maximum), optionally split by a
second dimension, and render it as a bar chart, line chart or stacked area. The
aggregation runs in the browser over the rows the server already filtered and
permitted, so a chart can never widen what a reader may see. Every chart carries
its definition, units and the row count it covers, and keeps a values table
beside the plot.

## Project layout

```
backend/
  app/
    api/v1/        REST endpoints, one module per workspace
    ai/            gateway, egress policy, prompts, schemas, orchestrator, adapters
    core/          config, errors, policy (roles and permissions), security
    db/            Mongo connection, collection registry, indexes
    integrations/  connector contract and the Jira / Azure DevOps / Asana adapters
    models/        Pydantic domain models (camelCase on the wire)
    repositories/  one repository per collection, optimistic concurrency
    services/      the domain logic: approvals, estimation, exports, sync, …
    workers/       durable queue and the background worker process
  tests/
    unit/          service level tests
    api/           functional tests over the real application
    acceptance/    the twenty numbered acceptance scenarios
    e2e/           live deployment checks
frontend/
  src/
    components/    shell, UI primitives, SVG chart primitives
    pages/         the fourteen workspaces of specification section 20
    i18n/          Greek and English interface dictionaries
    lib/           API client and session store
    __tests__/     unit and component tests
  e2e/             Playwright browser tests
scripts/           one entry point for the whole test suite
deploy/            MongoDB schema validation bootstrap
docs/              architecture, data policy, operations and traceability notes
```

---

## How the key requirements are implemented

### Approval cascade (section 10.2)

`backend/app/services/approvals.py`.

A **manifest** pins the exact `(item, version, content revision)` set for a
subtree, plus blockers, estimate totals, the diff against the previous approved
bundle and the client visible subset. Submitting carries the manifest hash; the
server rebuilds the manifest and refuses the whole operation with a refreshed
diff if anything moved. Nothing is marked approved or publishable until the
event's `committed` flag is set, so a staged write of a large bundle can never
look half approved. Inherited approvals reference the parent event, a new or
edited descendant marks the parent bundle as needing renewal, and revocation is
evaluated per version against the event that approved it.

### Data residency and the egress gate (section 8.3)

`backend/app/ai/egress.py`.

The gate is the only path from project content to a model and is default deny.
It refuses by classification, records an internal manifest of disclosure
*categories* (never payloads), minimises and sanitises what does leave, and
treats imported content as untrusted data so embedded instructions cannot
override policy. A cloud failure never causes a local only project to fall back
to cloud. The interface states plainly that sanitisation reduces disclosure and
is not a guarantee of anonymisation.

### Estimation (section 11)

`backend/app/services/estimation.py` implements the specification's formulas
literally, including the rule that a parent's initial rough estimate is kept for
comparison and never added to the child rollup, that story points and effort stay
independent with inconsistency warnings rather than forced equivalence, that
actual cost uses the rate effective on the work date, and that the focus factor
is never applied twice.

### Connectors (section 14)

`backend/app/integrations/` and `backend/app/services/integrations.py`.

Each adapter discovers what the destination actually supports before any mapping
is configured, and says so when it cannot: without credentials the compatibility
report is explicitly labelled as the provider's documented model rather than your
tenant. Jira's missing native feature level and Asana's missing hierarchy and
worklogs are surfaced as limitations, not silently flattened. Publication runs
through a transactional outbox with idempotency keys; inbound operational changes
apply immediately while specification or estimate changes raise a reviewable
change request, and concurrent edits surface as a field level three way conflict.

### Exports (section 16)

`backend/app/services/exports.py` enforces the real legacy `.xls` limits (65,536
rows, 256 columns), splitting with a manifest instead of truncating, escapes
formula like user text while keeping real numeric types, and emits the documented
JSON envelope with schema version, timezone, units and currency.

---

## Tests

```bash
scripts/run-tests.sh          # 257 checks, no infrastructure needed
scripts/run-tests.sh --all    # plus the live deployment and browser suites
```

On Windows PowerShell: `.\scripts\run-tests.ps1 [-All]`.

On Windows PowerShell: `.\scripts
un-tests.ps1 [-All]`.

On Windows PowerShell: `.\scripts
un-tests.ps1 [-All]`.

| Layer | Count | Infrastructure |
|---|---|---|
| Service level (`backend/tests/unit`) | 65 | none |
| API functional (`backend/tests/api`) | 112 | none |
| Acceptance scenarios AT-01 to AT-20 (`backend/tests/acceptance`) | 20 | none |
| Frontend unit and component (`frontend/src/__tests__`) | 60 | none |
| Live API end to end (`backend/tests/e2e`) | 11 | a running deployment |
| Browser end to end (`frontend/e2e`, Playwright) | 32 | a running deployment |

`docs/testing.md` describes each layer, the conventions and where a new test
belongs. The acceptance suite maps one test to each numbered scenario in
specification section 21:

```bash
cd backend && pytest -m acceptance -v
```

```
test_at01_mixed_language_evidence_is_associated_and_navigable
test_at02_unsupported_assumption_is_labelled_not_confirmed
test_at03_one_approval_covers_the_exact_descendant_manifest
test_at04_change_during_submission_fails_atomically
test_at05_a_new_story_is_not_covered_by_an_earlier_approval
test_at06_unreachable_local_model_pauses_without_cloud_fallback
test_at07_restricted_excerpt_is_blocked_and_recorded
test_at08_replayed_publication_and_webhook_create_no_duplicates
test_at09_concurrent_estimate_changes_surface_as_a_conflict
test_at10_external_status_does_not_change_approval_or_test_state
test_at11_client_is_denied_cost_reports_and_unrelated_sources
test_at12_parent_rough_estimate_is_a_comparison_value
test_at13_excel_and_json_exports_agree
test_at14_legacy_xls_splits_instead_of_truncating
test_at15_source_revision_produces_an_impact_report
test_at16_without_history_templates_are_used_and_no_accuracy_is_claimed
test_at17_a_candidate_that_does_not_improve_stays_inactive
test_at18_a_restored_dataset_keeps_its_links_and_rebuildable_index
test_at19_invalid_gherkin_blocks_the_artifact
test_at20_a_static_screenshot_raises_questions_rather_than_inventing
```

---

## Scope notes

Delivered against the specification's phases 1 to 4 as a working baseline. The
following are deliberately scoped as described in the specification itself and
need environment specific work before production use:

* **Local transcription and OCR** are queued and their absence is reported
  honestly: a recording is stored and marked as needing transcription rather than
  being treated as empty, and an image without an OCR worker is reported as
  unsupported. Attaching a locally produced transcript is supported today.
* **Connector adapters** make real API calls but have only been exercised against
  the documented contracts; validating them against live Jira, Azure DevOps and
  Asana tenants is Phase 0 work the specification already requires.
* **Figma and Adobe XD** import is covered by the export based path (screenshots,
  PDF, assets). Native `.xd` parsing stays behind the feasibility gate.
* **Vector retrieval** uses a local lexical index with Greek accent folding. The
  index is derived and rebuildable; a dedicated company hosted vector service can
  replace it without changing the retrieval interface.

## Documentation

| Document | Contents |
|---|---|
| `docs/decisions.md` | What the system is, every implementation decision and its cost, deviations from the specification, and what is deliberately unfinished |
| `docs/architecture.md` | Components, request path, data model, hierarchy and versioning, long running work |
| `docs/data-policy.md` | The egress gate, the classification decision table, what is recorded, failure behaviour |
| `docs/operations.md` | Installation, upgrade, rollback, backup and restore, scaling, observability, security posture |
| `docs/testing.md` | The six test layers, what each proves, the conventions and where a new test belongs |
| `docs/requirements-traceability.md` | Each numbered requirement of the specification mapped to the code that implements it |
