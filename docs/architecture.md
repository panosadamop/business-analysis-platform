# Architecture

## Components

| Component | Responsibility | Where |
|---|---|---|
| Web application | The fourteen workspaces, approval bundles, dashboards, reporting and the client portal | `frontend/` |
| API | Authentication, project APIs, policy enforcement, versioning, approval and synchronisation | `backend/app/api`, `backend/app/services` |
| AI workers | Evidence extraction, role orchestration, evaluation, exports and connector jobs | `backend/app/workers`, `backend/app/ai` |
| MongoDB | Primary records, immutable versions, relationships, policy configuration and job metadata | `backend/app/db` |
| Object storage | Originals, recordings, exports and large generated files | `backend/app/services/storage.py` |
| AI gateway | Model routing, egress policy, redaction, budgets, local and cloud adapters | `backend/app/ai/gateway.py` |
| Integration adapters | Provider discovery, mapping, webhooks or polling, reconciliation | `backend/app/integrations` |

The API and the worker run the same image as two processes. The worker scales
horizontally; job claiming is an atomic find-and-modify so two workers never run
the same job.

## Request path

```
browser ──▶ nginx (web)
              │  /api/* proxied, same origin
              ▼
         FastAPI (api)
              │  per request: bearer token ▶ user ▶ project membership ▶ permissions
              ▼
       service layer  ──▶ repositories ──▶ MongoDB
              │
              ├──▶ AI gateway ──▶ egress gate ──▶ local or cloud adapter
              └──▶ queue ──▶ worker (analysis, export, publish, sync)
```

Authorization is resolved once per request into a `ProjectContext` and then
enforced on every record, chunk, search result, report row, download and job
result. A client reviewer holds no project wide read permission at all: every
object they see is resolved through an explicit, non expired, non revoked share
grant.

## Data model

Bounded aggregates, referenced collections. No unbounded backlog, transcript or
audit log is ever embedded in a single document.

```
projects ──< projectMembers
         ──< sourceDocuments ──< sourceVersions ──< sourceChunks
                                                └─< transcriptSegments
         ──< requirements ──< requirementVersions
         ──< questions, glossaryTerms
         ──< backlogItems ──< artifactVersions        (immutable once approved)
         ──< estimates, rateCards, specifications
         ──< testCases ──< testVersions, testbooks
         ──< evidenceLinks, dependencyLinks           (many to many traceability)
         ──< analysisJobs ──< reviewFindings
         ──< approvalManifests ──< approvalEvents
         ──< baselines, changeRequests
         ──< iterations, allocations, worklogs, milestones, statusEvents
         ──< integrations ──< externalMappings, syncEvents, outboxJobs
         ──< shareGrants, comments
         ──< reportDefinitions, exportJobs
         ──< auditEvents, egressManifests, jobs
```

Key storage rules:

* `_id` holds the domain id; models never see the Mongo specific key.
* Every mutable document carries a `rev` optimistic concurrency token.
* Calendar dates are stored as ISO strings so they sort and compare correctly and
  round trip back into `datetime.date`; money is stored as a decimal string with
  an explicit currency; timestamps are UTC with the project timezone held
  separately.
* Compound unique indexes protect external mappings and idempotency keys.

## Hierarchy and versioning

`Project → Epic → Feature → Story → (Task)`. The parent type of each level is
validated on create and on move, and each item carries a materialised ancestor
`path` so a subtree read is a single indexed query.

Every content edit writes a new `artifactVersion`:

* editing a **draft** updates it in place but bumps its `rev`, which the approval
  manifest hash includes, so a concurrent approval still detects the change;
* editing an **approved** version branches a new draft, supersedes the old one
  and preserves it as the approved baseline;
* either way the ancestors with an existing approval are marked
  `requiresReapproval`.

## Long running work

Everything that can take time is a queued job with a status, progress, message,
attempt counter, cancellation flag and idempotency key: analysis runs, exports,
connector publication, connector polling and the daily metric snapshot. Analysis
jobs additionally store a per stage checkpoint, so a failed or paused run resumes
from the last validated stage rather than redoing completed work.
