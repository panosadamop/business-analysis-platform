# Project description and implementation decisions

Status: baseline implementation, 2026-10-01
Source of truth for scope: `AI_Analysis_Team_Software_Specification.md` version 1.0

This document describes what was built and records the decisions taken while
building it — including the places where the implementation deliberately differs
from the specification's proposals, and the places where it stops short and says
so. `requirements-traceability.md` maps each numbered requirement to the code and
`testing.md` describes how it is verified; this file explains the reasoning that
neither of those shows.

---

## 1. What the system is

An internal, company hosted application that operates as a coordinated AI team of
Business Analysts, Technical Analysts and QA Analysts. It takes project evidence —
briefs, meeting notes, Word and Excel documents, recordings, designs, schedules —
and turns it into reviewable requirements, a delivery backlog, estimates,
specifications and a testbook, keeping every claim traceable to the evidence it
came from or labelling it explicitly as an assumption.

Three properties shape the whole design:

1. **Nothing is published by the machine.** Every generated artifact is a draft.
   A human approver decides, and approving a parent approves its current
   descendant versions through a recorded, version bound cascade.
2. **Company data stays on company infrastructure by default.** Cloud processing
   is default deny at the deployment, the project and the role level, and a
   single gate is the only path from project content to a model.
3. **The product does not overstate itself.** Confidence values are decision
   aids, not probabilities. Sanitisation reduces disclosure, it does not
   anonymise. Generated tests are drafts, never "passed". Where a capability is
   missing — local OCR, a live connector tenant — the system says so instead of
   producing an empty or confident-looking result.

### Shape of the delivered system

| Part | Content |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, MongoDB 7. ~14,500 lines across API, services, AI orchestration, connectors, repositories and workers. |
| Frontend | React 18, TypeScript, Tailwind, Vite, TanStack Query. ~6,900 lines across the fourteen workspaces of specification section 20, plus sign in. |
| Tests | 300 automated checks in six layers; 257 need no infrastructure. See `docs/testing.md`. |
| Deployment | Docker Compose: api, worker, web, mongo, optional object store, optional local inference. |
| Documentation | `README.md`, plus architecture, data policy, operations, traceability and this file. |

---

## 2. Decisions

Each decision records the context, what was chosen, and what the choice costs.

### D-01 Python for the whole backend, not TypeScript with Python workers

**Context.** Section 17.1 proposes a TypeScript backend (for example NestJS) with
separate Python AI workers. The request was for Python and React.

**Decision.** One Python codebase serves the API and the AI workers, started as
two processes from one image (`uvicorn app.main:app` and
`python -m app.workers.worker`).

**Why.** The orchestration, extraction, estimation and export logic all touch the
same domain models. Splitting them across two languages would have duplicated the
model layer and the authorization rules — the two things that must never drift.

**Cost.** No Node runtime on the API side, so any future TypeScript-only library
would need a service boundary. The worker scales independently, so the shared
image does not constrain throughput.

### D-02 The manifest hash includes a content revision, not just a version number

**Context.** REQ-APP-04 requires the approval decision to be logically atomic: if
any included item changes between preview and submission, the whole operation
fails. The obvious implementation pins `(itemId, version)`.

**Decision.** The manifest hash pins `(itemId, versionId, version, contentRev,
referenceOnly)`, where `contentRev` is the `rev` counter of the stored version
document.

**Why.** Editing a *draft* updates it in place and keeps its version number. A
hash over version numbers alone would not notice that edit, and an approval
prepared before it would silently approve different content. This was caught by
`test_change_during_submission_fails_atomically`, which failed until the content
revision was included.

**Cost.** Any write to a version document — even a non-semantic one — invalidates
an open preview. That is the safe direction to fail in.

### D-03 Approval events carry an explicit `committed` flag

**Context.** The specification allows large bundles to be processed in stages but
forbids them from appearing approved or publishable before the final commit.
MongoDB multi-document transactions need a replica set, which not every
deployment will have.

**Decision.** The event is written with `committed: false`, the descendant updates
are applied (inside a transaction where the deployment supports one, sequentially
otherwise), and only then is `committed` set to `true`. Every consumer —
publication, baselines, the approval history — filters on `committed`.

**Why.** It gives the same externally visible guarantee on a single node as on a
replica set: a partially applied cascade is never treated as an approval.

**Cost.** One extra write per decision, and consumers must remember the filter.
The compose file provisions a single node replica set so the transactional path
is the default.

### D-04 A deterministic local analyst is the default model

**Context.** The system must be usable in a local-only deployment, and the test
suite must not depend on a model being available. Section 8.3 requires
interchangeable local and cloud adapters.

**Decision.** `HeuristicLocalAdapter` is a transparent, rule based analyst: it
extracts requirement candidates from obligation wording (`must`, `shall`,
`πρέπει`), raises questions from ambiguity markers (`TBD`, `ασαφές`), clusters
them into an epic/feature/story skeleton, derives candidate data entities and API
operations, and generates positive, negative and boundary tests with Gherkin —
all with citations to real evidence locators and provenance marked
`ai_suggestion`.

**Why.** The product works with zero configuration and zero model weights, the
output is reproducible (same evidence in, same analysis out), and the shape of
every artifact is exercised end to end in CI. `LocalHttpAdapter` (any
OpenAI-compatible company-hosted server) and the cloud adapters implement the
same contract and are a configuration change away.

**Cost.** The heuristic analyst's wording is mechanical and its clustering is
shallow — it is a baseline, not a substitute for a model. It is labelled as a
proposal everywhere it appears, which is what the specification requires of any
generated content anyway.

### D-05 One egress gate, default deny, with a manifest of categories

**Context.** Section 8.3 and NFR-02. The risk is not just an unintended cloud
call, it is an implementation where several code paths each decide policy
slightly differently.

**Decision.** `app/ai/egress.py` is the only path from project content to a model.
It decides allow/deny, minimises and sanitises the payload, and writes an
`egressManifest` for both outcomes. Adapters never decide policy. Cloud needs
three independent switches on: deployment, project, and optionally role.

**Why.** A single choke point can be read, tested and audited. The manifest
records disclosure *categories*, redaction *counts* and a payload hash — never the
payload — so the audit trail does not become a second copy of the sensitive data.

**Cost.** Every new model-touching feature must route through the gateway. That
is the intent.

### D-06 Client access is resolved only through share grants

**Context.** Section 4 requires that client users never see internal rates,
prompts, confidential evidence or internal comments, and section 15 requires
version-scoped sharing.

**Decision.** The `client_reviewer` role carries exactly one permission —
`client.comment`. It holds no project-wide read permission at all. Everything a
client sees is resolved from an explicit, non-expired, non-revoked grant listing
`(itemId, version)` pairs, served by a separate `/client/...` API surface, with a
server-side field strip applied on the way out.

**Why.** Filtering a project-wide read is a permission model that fails open when
a new field is added. Resolving from a grant fails closed.

**Cost.** Client-facing features need their own endpoints rather than reusing the
internal ones. Verified by test: a client token receives `403` on the project,
backlog and cost endpoints, and the shared payload contains no cost, rate, prompt
or model field.

### D-07 Rate and cost columns are permission-gated in the report layer itself

**Context.** REQ-REPORT-08 requires server-side column restriction including
fields *derived* from hidden costs, and that a saved template cannot grant
permissions its reader lacks.

**Decision.** Each report column declares `requires: Permission` and
`clientSafe: bool`. `allowed_columns()` is applied on preview, on export and on
template save; a template naming a denied field is rejected with `403` rather
than silently narrowed.

**Why.** Narrowing silently teaches users that a template "works" and then
produces different output per reader, which is how derived cost values leak.

**Cost.** Adding a dataset means declaring the permission for each column. The
allowlist is also what keeps report queries free of client-supplied fragments
(REQ-REPORT-03).

### D-08 Dates stored as ISO strings, money as decimal strings

**Context.** BSON cannot encode `datetime.date`, and floats cannot represent
money exactly. Section 18 requires decimal-safe money with an explicit currency
and UTC timestamps held separately from the project timezone.

**Decision.** The repository layer encodes on write: `date` becomes an ISO string
(sorts and range-compares correctly, round-trips back through Pydantic),
`Decimal` becomes a string, `datetime` stays a BSON date. `Money` is
`{amount: "1234.56", currency: "EUR"}` and refuses to add across currencies.

**Why.** Found by a failing test, not by review: rate cards would not persist at
all. Encoding once in the repository means no service has to remember.

**Cost.** Date range queries compare strings. For ISO-8601 that is correct, but it
is a convention the next developer must know — hence this entry.

### D-09 A custom email type instead of `EmailStr`

**Context.** `email-validator` rejects reserved and special-use domains, including
`.local`, which internal company deployments commonly use. The seed data used
`@company.local` and failed validation.

**Decision.** `app.models.common.Email` validates shape and normalises case, and
accepts internal domains.

**Why.** Refusing a company's own internal mail domain is the validator being
wrong about this context, not the data being wrong.

**Cost.** Slightly weaker validation of genuinely malformed public addresses. The
shape check still rejects anything without a local part, `@` and a dotted domain.

### D-10 `bcrypt` directly, not `passlib`

**Context.** `passlib` 1.7.4 is incompatible with `bcrypt` 4.1+ — it fails to read
the version and then errors on hashing.

**Decision.** Call `bcrypt` directly, truncating the encoded password to 72 bytes
explicitly (bcrypt's own limit) rather than failing on long passphrases.

**Cost.** None meaningful; `passlib`'s scheme-migration machinery was not in use.

### D-11 MongoDB-backed job queue instead of Redis or Celery

**Context.** NFR-05 requires long-running work to be queued, observable and
restartable without duplicate approved artifacts or remote items.

**Decision.** A `jobs` collection with atomic claim (`findOneAndUpdate`),
idempotency keys as a unique partial index, exponential backoff, dead lettering,
and recovery of jobs whose worker died. Connector publication adds a transactional
outbox on top.

**Why.** One fewer service to deploy, back up and secure in a company-hosted
installation, and the job records are queryable with the same tools as everything
else. The volumes here — analysis runs, exports, connector syncs — are far below
where a dedicated broker earns its operational cost.

**Cost.** Polling rather than push, so a job starts within about a second rather
than instantly. If throughput ever demands it, the queue interface is small enough
to swap.

### D-12 Lexical retrieval with Greek accent folding, not a vector service

**Context.** REQ-KNOW-07 requires permission-filtered keyword and semantic search
in Greek and English. Section 17.1 makes a separate vector service optional.

**Decision.** A TF-IDF ranker over source chunks with Unicode normalisation that
strips Greek accents, so `Πελάτης` matches `πελατης`. Classification filtering is
applied before ranking, not after.

**Why.** It works offline, needs no embedding model, and the retrieval interface
(`search`, `retrieve_context`) is narrow enough that a company-hosted vector
service can replace the implementation without touching callers. The index is
derived data and is rebuildable from the authoritative sources, as the
specification requires.

**Cost.** No true semantic matching — a synonym the evidence never uses will not
be found. Flagged in the README scope notes.

### D-13 Connector discovery states what it does not know

**Context.** Section 14.1 requires discovery before configuration, and warns
against assuming equivalent native hierarchies.

**Decision.** Without credentials, each adapter returns a capability report built
from the provider's *documented* model, with a limitation that says exactly that
and tells the operator to re-run discovery after storing credentials. Jira's
missing guaranteed level between epic and story, Azure DevOps's process-dependent
story type, and Asana's absent hierarchy and worklogs are each surfaced as
limitations with a concrete fallback strategy.

**Why.** A connector that silently invents a mapping is worse than one that
refuses, because the loss shows up later as missing scope in the delivery tool.

**Cost.** An extra step before publication: mapping approval is required and is
revoked automatically whenever a mapping changes.

### D-14 Object storage behind a Compose profile

**Context.** Section 17.1 requires company-hosted object storage for originals,
recordings and exports. On the build machine the MinIO image could not be pulled
from any registry.

**Decision.** MinIO is defined in `docker-compose.yml` under the `object-store`
profile. Without it the API writes the same files to the persistent,
company-controlled `api-storage` volume — the fallback that `services/storage.py`
already implements. `docker compose up` therefore works on a restricted network;
`docker compose --profile object-store up -d` is the recommended production form.

**Why.** Data residency is unchanged either way: both paths stay on the host. The
alternative — a default stack that cannot start — trades a real property for a
cosmetic one.

**Cost.** An operator who never reads the README gets volume storage rather than
object storage. The README and `operations.md` both call it out.

### D-15 The worker has its own liveness signal

**Context.** The worker runs from the API image and inherited its HTTP health
check, so it reported unhealthy forever despite working correctly.

**Decision.** The scheduler touches a heartbeat file every tick; the worker's
health check asserts the file is less than five minutes old.

**Why.** It distinguishes a live worker from a hung one, which a process check
would not.

### D-16 The test suite is layered, and only the last two layers need a stack

**Context.** "Does the system work" is several different questions: is a formula
right, does an endpoint enforce a permission, does the agreed acceptance scenario
hold, does the real deployment behave.

**Decision.** Six layers (`docs/testing.md`): service level, API functional over
the real application, an acceptance suite named one test per AT scenario,
frontend unit and component, live deployment, browser. The first four run against
an in memory database substitute and need nothing installed beyond Python and
Node; the last two are skipped unless a deployment URL is supplied.

**Why.** 257 of the 300 checks run anywhere, in about five minutes, so there is
no excuse not to run them. The live layers then cover precisely what a substitute
cannot: transactional commits on a replica set, the worker consuming its queue,
nginx routing and the browser.

**Cost.** Two database behaviours to keep in mind rather than one. The substitute
does not enforce unique indexes or return timezone aware datetimes, which is why
`as_utc` exists (D-08's neighbour) and why the live suite runs in CI on every
merge.

A second cost is fixture discipline. Service level tests build domain objects
directly, while API and acceptance tests need signed in HTTP actors, and both
wanted a fixture called `project`. They live apart on purpose: model fixtures in
`tests/unit/conftest.py`, HTTP fixtures in `tests/support.py`, re-exported from
the root `conftest.py`. A single shared fixture namespace silently resolved to
the wrong `project` and produced failures that looked like application bugs.

### D-17 Charts carry their own definition, units and freshness

**Context.** Section 12 requires charts to expose metric definitions, units,
filters, as-of time and data freshness, and to disclose data sufficiency.

**Decision.** Every chart endpoint returns a `ChartResponse` carrying those fields
plus `insufficientData` and warnings, and the frontend renders them beneath the
plot rather than leaving them to a tooltip. Charts never mix units on one axis,
and the burndown unit is an explicit choice.

**Why.** A delivery chart without its definition is where planned-versus-actual
arguments start.

**Cost.** Slightly larger payloads and a fixed chart frame. Each chart also ships
a values table, which doubles as the accessibility path for the two palette
colours that sit below 3:1 contrast on the light surface.

### D-18 Readiness is answerable through the published surface

**Context.** The API serves `/health` and `/ready`, but only the web tier is
published. An orchestrator probing the deployment reached nginx, whose catch all
returned the application shell with a 200 — a readiness probe that can never
fail is worse than none.

**Decision.** nginx owns `/health` (its own liveness, plain text) and proxies
`/ready` to the API, so the published surface reports the state of the stack
behind it. Both are exact location matches, so neither falls through to the
single page application.

**Why.** Found by the live end to end suite, which asked the published URL for
JSON and got HTML. The probe an operator will actually use is the one that has
to be right.

**Cost.** One more route the web tier knows about. The internal API port stays
unpublished.

### D-19 A platform owner role, which section 4 deliberately does not have

**Context.** Section 4 draws a line the specification is explicit about: a system
administrator configures infrastructure, identity and connectors, and *"content
access requires a separate project entitlement"*. No role in the specification
owns every project. The operator asked for one: a superuser with ownership of
everything.

**Decision.** A `superuser` platform role that holds every permission in every
project without needing a membership record. It is granted through
`PATCH /admin/users/{id}` by an existing administrator, and the seeded deployment
ships one account with it (`owner@company.local`).

**Why it is implemented as an entitlement, not a bypass.** The authorization
checks are unchanged — every endpoint still asks `ctx.require(...)` for the
permission it needs. The role simply grants all of them, so a future permission is
covered automatically and nothing routes around the checks. Three further
properties keep the exception honest:

* reaching a project the owner is not a member of writes a
  `project.accessed_as_owner` audit event naming the standing used;
* granting or removing the role is itself audited, and the deployment refuses to
  remove the last active owner;
* the role changes nothing for client reviewers. A client still sees only what a
  share grant lists, and the client deny list still applies.

**Cost, stated plainly.** This is a genuine divergence from the specification, and
it concentrates risk: one compromised account reaches every project's content,
including evidence and rates. The audit trail records that it happened; it does
not prevent it. If that trade is not wanted, remove `Role.SUPERUSER` from
`ROLE_PERMISSIONS` and the deployment reverts to the specification's separation
with no other change.

### D-20 Everything the workflow generates can also be written by hand

**Context.** The analyst workflow produces requirements, questions, backlog items,
specifications and tests. An analyst who spots something the analysis missed had
no way to add it without re-running a stage, and some artifacts had no create
endpoint at all.

**Decision.** Every artifact type has a create path, in the API and in the
interface: requirement, question, glossary term, specification (narrative, Mermaid
diagram or structured JSON), evidence link, test case with Gherkin, sprint,
milestone, allocation and rate card. The forms live together in
`frontend/src/components/entry-forms.tsx`.

**Why.** The specification treats generated content as a proposal and the analyst
as the author of record. A product where the machine is the only way to create an
artifact contradicts that. Writing by hand also makes the provenance choice
explicit: the requirement form asks whether a statement is evidence backed, an
analyst assumption or a client decision, rather than inferring it.

**Cost.** More surface to keep consistent. A hand written entry follows exactly
the same rules as a generated one — it starts as a draft, its Gherkin is validated
before it is saved, and it needs the same editing permission — so the rules live
in one place rather than two.

### D-21 Report charts are computed in the browser, over permitted rows only

**Context.** The report builder returned tables. A chart needs a category and a
measure, which could be computed on the server or in the browser.

**Decision.** The browser groups the rows the preview already returned
(`frontend/src/components/report-chart.tsx`): a grouping column, an optional
second dimension, and sum, count, average, minimum or maximum.

**Why.** The server has already applied the dataset allowlist and the caller's
column permissions, so charting cannot widen what a reader may see — a chart can
only aggregate rows that were permitted. It also keeps the chart interactive
without a round trip per change, and reuses the same chart primitives as the
dashboards, so the colour, legend and values table rules hold.

**Cost.** The chart covers the previewed page rather than the whole dataset, so
the preview limit (500 rows) bounds it. The chart states the row count it covers;
for a full dataset the export is the right tool.

---

## 3. Deviations from the specification

| Specification proposal | What was built | Reason |
|---|---|---|
| TypeScript backend (NestJS) + Python AI workers | Python for both, one image, two processes | Requested stack; avoids duplicating the domain model (D-01) |
| Separate vector index service | Local lexical index with Greek folding, same interface | Optional per section 17.1; rebuildable derived data (D-12) |
| Redis or similar durable queue | MongoDB-backed queue with outbox | Fewer services to operate; interface is swappable (D-11) |
| MinIO always on | MinIO behind a Compose profile, volume fallback | Image unavailable on the build network; residency unchanged (D-14) |
| **No role owns every project** (section 4: content access needs a project entitlement) | **A `superuser` platform role that does** | **Explicitly requested. Implemented as a standing entitlement with its own audit trail, not as a bypass (D-19)** |

Everything else follows the specification's structure, including the collection
layout of section 18, the API outline of section 17.3 and the fourteen screens of
section 20.

---

## 4. What is deliberately not finished

These are scoped exactly as the specification itself scopes them. None of them is
hidden behind a plausible-looking empty result.

* **Local transcription and OCR.** A recording is stored and marked as requiring
  transcription; an image without an OCR worker is reported as unsupported. A
  locally produced transcript can be attached today and becomes timestamped,
  correctable segments. Wiring a transcription worker is a configuration and
  hardware decision (Phase 0 in the specification).
* **Legacy `.doc`.** Needs the isolated conversion worker; reported as
  unsupported rather than parsed badly.
* **Connector adapters against live tenants.** The HTTP calls are real and the
  mappings follow each provider's documented model, but they have not been run
  against a live Jira, Azure DevOps or Asana tenant. Section 22 Phase 0 requires
  exactly that validation.
* **Figma and Adobe XD.** Covered through the export-based path (screenshots, PDF,
  assets). Native `.xd` parsing stays behind the specification's feasibility gate.
* **Manual test execution tracking.** Out of initial scope per section 13; the
  testbook records review state only and never a run status.
* **Performance targets (NFR-04, NFR-06, NFR-07).** Queries are project-scoped and
  indexed and long work is queued, but the 10,000-story reference load, the
  availability objective and the restore drill have not been measured. They are
  acceptance targets to validate on an agreed deployment, not claims.

---

## 5. Verification performed

Reproduce with `scripts/run-tests.sh --all` against a deployment started by
`docker compose up -d` and seeded with `docker compose run --rm seed`.

| Check | Result |
|---|---|
| Backend service level suite | 65 passed |
| Backend API functional suite | 112 passed |
| Acceptance scenarios AT-01 to AT-20 | 20 passed |
| Frontend unit and component suite | 60 passed |
| Live deployment suite | 11 passed against the running stack |
| Browser suite (Playwright, Chromium) | 32 passed against the running stack |
| Frontend type check and production build | clean |
| Seed against real MongoDB 7 replica set | 15 requirements, 5 questions, 6 epics, 6 features, 10 stories, 5 specifications, 47 tests |
| Approval cascade over HTTP | 13 manifest entries, 1 explicit and 12 inherited, `committed: true` |
| Replayed approval submission | `409 version_conflict`, nothing approved |
| Client isolation over HTTP | `403` on project, backlog and cost; shared payload free of internal fields |
| Exports | `.xlsx` and JSON row counts agree; `.xls` splits at 65,536 rows with a manifest |
| Docker Compose stack | api, worker, web and mongo all healthy; SPA served and API proxied |
| Platform owner on the live stack | reads every project with no membership, reaches all nine project surfaces, access recorded as `project.accessed_as_owner` |
| Manual entry on the live stack | requirement, question, glossary term, specification, evidence link, test case, sprint and milestone each created through the API |

---

## 6. What the automated suite caught

The suite was written after the implementation, so the defects below are the
measure of what it is worth. Each is fixed, and each now has a test that fails if
it returns.

| Defect | Where | Found by |
|---|---|---|
| A Kanban WIP limit of `0` was treated as "no limit", because the check tested truthiness rather than presence. A column meant to hold nothing silently accepted work. | `api/v1/planning.py` | API functional test |
| A rejected sign in showed "Your session has expired" instead of the server's "Email or password is incorrect". The generic 401 handler, meant for an expired token on any other call, swallowed the real message and redirected. | `frontend/src/lib/api.ts` | Browser end to end test |
| Comparing a stored timestamp with `utcnow()` raised `TypeError` when the driver returned a naive datetime, so an expired membership crashed the request instead of being refused. | `api/deps.py`, `services/sharing.py` | API functional test |
| The worker inherited the API image's HTTP health check and reported unhealthy forever while working correctly. | `docker-compose.yml`, `workers/worker.py` | Docker deployment check |
| `/ready` through the published surface returned the application shell with a 200, so the probe could not fail. | `frontend/nginx.conf` | Live end to end test |

Two earlier findings came the same way during implementation, before the suite
was formalised: the approval manifest hash missed in place draft edits (D-02),
and `datetime.date` values could not be stored at all (D-08). Both are recorded
as decisions above because they changed the design, not just the code.

### Known state of the running deployment

The nginx readiness change is correct in source and was verified against the
live container, but that container received it through `docker compose cp` and a
reload: Docker Hub rate limited the `nginx:1.27-alpine` pull at the time, so the
image could not be rebuilt. The next successful build picks it up. Nothing else
depends on it.
