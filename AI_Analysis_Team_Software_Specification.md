# AI Analysis Team — Software Requirements and Technical Specification

Version: 1.0  
Date: 2026-10-01  
Audience: Product owners, business analysts, architects, developers, QA and delivery managers  
Status: Proposed implementation baseline; subject to stakeholder approval

## 1. Purpose

Build an internal, company-hosted application that operates as a coordinated AI team of Business Analysts, Technical Analysts and QA Analysts. It transforms project evidence into reviewable requirements, delivery backlogs, estimates, specifications and testbooks; supports client collaboration; and maintains traceability throughout delivery.

The application shall support Greek and English, local and cloud AI, Docker deployment, a NoSQL primary database, Scrum and Kanban, and bidirectional integration with Jira, Azure DevOps and Asana. Every generated artifact requires human approval. Approving a parent item shall automatically approve its current descendant versions through a recorded cascade.

“Shall” indicates a required capability. “Should” indicates a recommended capability. Technical component choices and sizing below are proposed defaults, not decisions explicitly made by the requester.

## 2. Confirmed Scope and Proposed Defaults

| Area | Requirement or default |
|---|---|
| Audience | Internal staff with controlled client access to selected projects and artifacts |
| Inputs | Briefs, recordings, meeting notes, designs, Word/Excel documents, schedules and supporting files |
| AI | Local and cloud model adapters; sequential BA → Technical Analyst → QA checks |
| Residency | Originals, recordings, transcripts, extracted content, embeddings and internal logs stay on company-controlled infrastructure |
| Cloud policy | Disabled by default per project; only explicitly permitted, minimized, sanitized context may leave company infrastructure |
| Languages | Greek and English input, interface and output; output language independent of source language |
| Approval | Human approval with parent-to-descendant approval inheritance tied to exact versions |
| Delivery | Scrum and Kanban; capacity, progress, actual effort and baseline comparison |
| Estimates | Story points, person-hours, person-days, role-based cost and later historical calibration |
| Generated outputs | Epics, features, stories, acceptance criteria, functional/NFR specifications, process diagrams, data models, API specifications and descriptive/Gherkin tests |
| Integrations | Bidirectional Jira, Azure DevOps and Asana; no connector priority was specified |
| Exports | Markdown specifications, Excel .xlsx and legacy .xls reports, versioned JSON; Gherkin .feature files |
| Deployment | Docker; proposed MongoDB primary persistence and company-hosted object storage |

Recommended additions from the clarification discussion are included: source traceability, ambiguity resolution, change impact, versioning, quality gates, dependencies, report templates, permissions and audit history. Manual test execution tracking is a later enhancement; generating executable automation code is outside this scope.

Cloud AI cannot analyze company content without receiving some content. Keeping original files locally does not mean zero data disclosure. The product shall explain this distinction and provide a strict local-only mode that blocks all project-derived cloud payloads. Sanitization reduces disclosure; it shall not be presented as a guarantee of anonymization.

## 3. Goals and Boundaries

### 3.1 Goals

- Reduce preparation time for analysis and QA documentation while maintaining accountable human review.
- Make every delivery requirement and test traceable to evidence or an explicitly labeled assumption.
- Maintain an approved scope baseline and show the effect of subsequent changes.
- Produce practical, tool-compatible backlog items and transparent initial estimates.
- Compare planned effort, capacity, cost and schedule against actual execution.
- Give clients a controlled review experience without exposing internal rates, notes or unrelated projects.

### 3.2 Outside the Initial Scope

- Autonomous publication of unapproved generated content.
- Automatic source-code implementation or executable test automation.
- Replacement of Jira, Azure DevOps or Asana as complete engineering platforms.
- Guaranteed accurate estimates, automatic model improvement without evaluation, or inference of complete business behavior from screenshots alone.
- Public multi-company SaaS billing. Maintain project/client isolation so later expansion remains possible.
- Native mobile apps and live meeting-bot capture; uploaded recordings are required initially.

## 4. Roles and Authorization

| Role | Typical permissions |
|---|---|
| System administrator | Infrastructure configuration, identity integration, provider and connector management; content access requires a separate project entitlement |
| Project administrator | Membership, project policies, sharing configuration, workflow and baselines |
| Lead analyst / designated approver | Review, edit, approve or reject artifacts and descendant bundles |
| Business analyst | Sources, business requirements, questions, functional specifications and backlog drafting |
| Technical analyst | Dependencies, technical requirements, data models, APIs and technical reviews |
| QA analyst | Acceptance criteria, descriptive tests, Gherkin and testbook reviews |
| Delivery manager | Capacity, schedules, estimation, budgets, progress and reports |
| Contributor | Assigned editing, comments and actual time entry |
| Client reviewer | Read and comment on explicitly shared versions; optional acceptance authority granted per project |
| Internal viewer | Read permitted artifacts and reports |

Authorization shall be enforced server-side on records, source chunks, search, reports, downloads and job results. Client users shall never see internal rate cards, AI prompts, confidential evidence or internal comments unless explicitly shared. Internal readiness approval and client business acceptance shall be separate records; a project may require both before publication.

Company SSO via a configurable OIDC identity provider is recommended. Client access shall support authenticated invitations, expiry and revocation. Public anonymous sharing shall be disabled by default. Revocation prevents future access but cannot recall already downloaded files.

## 5. Main User Journey

1. Create a project, select languages, delivery method, working calendar, members and confidentiality policy.
2. Upload or import evidence and select its authority, version, scope and access classification.
3. Review extraction/transcription, identify speakers and correct uncertain passages.
4. Run the BA analysis; review the evidence inventory, business rules, questions and proposed hierarchy.
5. Run Technical Analyst review and revisions; run QA review and revisions.
6. Resolve critical questions, edit artifacts and estimates, and inspect the traceability and quality report.
7. Preview a parent approval bundle, including every descendant and attached acceptance/test artifact.
8. Approve the current bundle; create an approved baseline and optionally share selected versions with the client.
9. Preview connector mappings and publish approved content through a tracked job.
10. Synchronize execution data, record actual effort and update capacity.
11. Review dashboards, scope changes and forecast revisions; build and export reports.

All long-running operations shall display progress, cancellation, warnings, partial outcomes and retry options.

## 6. Evidence Ingestion

### 6.1 Supported Inputs

| Input | Required treatment | Evidence locator |
|---|---|---|
| Briefs / meeting notes | Rich text, Markdown, text and PDF; headings and structured extraction | Heading, paragraph or page |
| Word | .docx; tables, headings, comments and tracked-change visibility; legacy .doc via isolated conversion | Section/table/paragraph; page where available |
| Excel | .xlsx and .xls; sheets, tables, formulas and cached values; no macro execution | Workbook, sheet and cell range |
| CSV / JSON | Encoding and schema detection with import preview | Row/key path |
| Recordings | Common audio/video formats; local audio extraction, transcription and speaker diarization | Start/end timestamps and speaker label |
| Figma | Authorized file/node import plus exported screenshots/PDF/assets fallback | File, node ID and imported revision |
| Adobe XD | Exported screens, PDF, assets and supplied interaction notes; native .xd parsing optional after feasibility validation | Artboard/export identifier and version |
| Schedules | Spreadsheet/CSV import of milestones, dependencies, dates and allocations | Row, milestone ID and version |
| Other technical documents | PDF, text, images with local OCR and structured API files | Page, block or schema path |

Design import shall distinguish observed UI facts from inferred business behavior. A screen without interaction metadata shall trigger questions about navigation, validation, permissions and error states. The system shall not promise a universal XD server API or complete native-file support without validating the actual project assets and available tooling.

### 6.2 Processing Requirements

- Store originals with hashes, uploader, upload time, classification, source revision and project ownership.
- Scan uploads; validate file signatures, size and supported codecs. Parse files in isolated workers without macros, scripts or external-link execution.
- Configure file size, duration and processing limits; show limits before upload. Proposed defaults: 100 MB per document and 2 GB per recording, subject to load validation.
- Preserve both original and normalized text; record extractor version and warnings.
- Handle password-protected, corrupt or unsupported files with an actionable failure; never silently treat extraction failure as missing requirements.
- Identify duplicates and revisions using hashes and metadata. Re-imports shall create versions rather than overwrite evidence history.
- Mark low-confidence OCR/transcription spans for correction. Diarization labels shall be user-correctable and shall not imply verified speaker identity.
- Extract meeting decisions, actions, owners, dates, open questions and requirement candidates; preserve timestamps.
- Treat spreadsheet formula values as potentially stale; never silently claim recalculated values. Record whether values were cached or locally recalculated.
- Allow source inclusion/exclusion, sections to ignore, and authority rankings. Conflicting evidence remains visible until an analyst records a resolution.
- No external design or document import shall bypass access permission or company egress policy.

## 7. Knowledge, Requirements and Traceability

**REQ-KNOW-01:** Maintain a project glossary, stakeholders, goals, scope boundaries, assumptions, constraints, business rules, decisions and open questions.

**REQ-KNOW-02:** Normalize extracted requirements with stable IDs, type, source links, business value, priority, confidence, owner and lifecycle state.

**REQ-KNOW-03:** Maintain many-to-many links across source evidence → requirements → epics/features/stories → acceptance criteria → tests → specifications and external items.

**REQ-KNOW-04:** Provide source viewers that open the referenced paragraph, cells, design node or recording segment. Unauthorized users see a restricted-source indication rather than leaked text.

**REQ-KNOW-05:** Detect ambiguity, contradictions, duplicate requirements, missing rules and incomplete flows. Create a question register with severity, proposed clarification, owner and resolution history.

**REQ-KNOW-06:** Distinguish evidence-backed requirements, analyst assumptions and AI suggestions. Confidence indicators are decision aids, not calibrated probabilities unless validated.

**REQ-KNOW-07:** Provide permission-filtered keyword and semantic search in Greek and English. Deleted or revoked evidence shall be removed from active retrieval indexes and caches.

**REQ-KNOW-08:** Detect changed evidence and generate an impact list. Existing approved artifacts remain historically available but affected current artifacts are marked potentially stale until reviewed.

## 8. Sequential AI Analyst Workflow

### 8.1 Roles and Outputs

| Stage | Responsibilities | Required outputs |
|---|---|---|
| Business Analyst | Goals, scope, stakeholders, business rules, flows and backlog decomposition | Requirements, questions, epics/features/stories, initial criteria and functional specification |
| Technical Analyst | Feasibility, architecture assumptions, integrations, data, NFRs and dependencies | Findings, revised technical content, data models, API contracts, effort drivers and dependencies |
| QA Analyst | Testability, coverage, boundaries, negative paths and consistent criteria | QA findings, refined criteria, descriptive/Gherkin tests and coverage matrix |

The orchestrator shall execute BA → Technical Analyst → QA in sequence on explicit artifact versions. Each stage shall use shared project evidence and produce structured findings with severity, rationale and citations. A specialist review shall not count as human approval.

### 8.2 Orchestration and Quality Controls

- Validate outputs against versioned JSON schemas and required fields before saving artifacts.
- Preserve role, model identifier, model configuration, prompt-template version, input evidence versions, output version, time, token usage and cost where available.
- Role revisions shall create new drafts with diffs. Human edits shall be preserved; regeneration requires an explicit scope and merge preview.
- Configure a bounded correction loop, proposed maximum three cycles. Unresolved findings are escalated rather than endlessly reprocessed.
- Critical blockers include inaccessible evidence essential to a claim, unresolved critical contradiction, missing acceptance criteria, invalid hierarchy and untestable mandatory requirements.
- A human approver may waive a blocker with rationale; waivers are visible in the approval bundle and audit record.
- Label architectural proposals and inferred requirements explicitly. Never invent confirmed client decisions or source references.
- Treat imported content as untrusted data. Embedded instructions shall not override system policy, grant tool access or initiate external writes.
- AI agents cannot access arbitrary URLs, secrets or production tools. External mutations run through authorized deterministic services.
- Store job checkpoints and allow resume from the last validated stage after failure.

### 8.3 Model Routing and Data Policy

Provide interchangeable local/cloud adapters with per-role selection, model capability metadata, health checks and budgets. Local-only projects shall remain functional for ingestion, retrieval and generation with a supported local deployment.

| Classification | Local treatment | Cloud treatment |
|---|---|---|
| Restricted | Local processing only | Blocked |
| Confidential | Local by default | Only project-authorized sanitized/minimized excerpts after policy validation |
| Shareable | Local retained master | Permitted approved context under configured provider policy |

Transcription, OCR, embeddings and source indexing shall be local by default. Cloud payload preparation shall remove unnecessary identities, secrets and sensitive data, show the disclosure categories and apply an outbound policy gate. Store an internal audit manifest of what was sent; do not put sensitive payloads into ordinary logs.

Cloud/provider failure shall never cause a local-only project to fall back to cloud. Provider retention/training settings, network destinations and contracts must be validated during implementation; the specification does not assert that all providers support identical privacy controls. Connector publication is a separate approved disclosure to the configured external project-management service; originals and recordings are never attached automatically.

## 9. Backlog and Specifications

### 9.1 Canonical Hierarchy

The internal hierarchy shall be Project → Epic → Feature → User Story, with optional delivery tasks under stories. All three required levels shall have initial estimates, acceptance criteria, priorities, owners, dependencies, source links and version states.

A user story shall contain:

- Stable ID, title, actor, need and business benefit.
- Full description, scope exclusions and applicable business rules.
- Priority, business value, release/sprint, labels and owner.
- Acceptance criteria with IDs and observable outcomes.
- Design, requirement and evidence references.
- Functional, technical and NFR notes; assumptions and unresolved questions.
- Dependencies and risk/complexity drivers.
- Story-point estimate, role-based effort range, derived person-days and estimated cost.
- Linked descriptive and Gherkin tests, review findings and approval status.

Epic/feature criteria shall express outcome-level acceptance; story criteria shall express detailed observable behavior. Completing all child stories does not automatically prove that a cross-cutting parent outcome has been validated.

### 9.2 Generated Specifications

| Deliverable | Minimum content |
|---|---|
| Functional specification | Scope, actors, flows, rules, permissions, validations, exceptions and requirement IDs |
| Non-functional specification | Measurable target, context, verification method and accountable owner for each NFR |
| Process diagrams | Main, alternate and error flows; named actors and requirement links; Mermaid source/render initially |
| Data models | Entities/documents, fields, types, requiredness, relationships, uniqueness, lifecycle and privacy classification |
| API specifications | Proposed OpenAPI document, operations, auth, schemas, validation, errors, pagination, idempotency and example payloads |
| Project testbook | Versioned test plan, suites, cases, Gherkin, coverage, assumptions, environments and release scope |

Generated API specifications describe the client's proposed project APIs. The application's own management API is specified separately in Section 17. Validate generated contracts structurally; do not imply that they have been implemented or runtime tested.

## 10. Approval, Versioning and Baselines

### 10.1 States

Draft → In Review → Approved or Rejected. Approved versions are immutable. Editing produces a new Draft version. Archived and Superseded describe historical lifecycle states separately from execution status.

### 10.2 Parent Approval Cascade

**REQ-APP-01:** Approving an epic shall approve its current feature/story/task descendants and their owned acceptance-criteria and test artifacts. Feature approval applies to its corresponding subtree. Project-level approval may apply to a selected full release bundle.

**REQ-APP-02:** Before approval, display an exact version manifest, item counts, outstanding findings, estimate totals, differences from the prior approved bundle and client-visible content. The cascade is the default parent-approval behavior.

**REQ-APP-03:** The approver must have authority over all included descendants. Linked artifacts owned by other subtrees are references and shall not silently acquire approval. Critical findings require resolution or explicit recorded waiver.

**REQ-APP-04:** Approval is a logical atomic operation: either the exact manifest is approved or none of it is. Use version locks/optimistic concurrency. If any item changes during review, reject the operation with a refreshed diff. Large bundles may be processed in stages but shall not appear approved or publishable before final commit.

**REQ-APP-05:** Record actor, time, parent decision, every descendant version, explicit versus inherited approval and waivers. Inherited approvals shall reference the parent approval event.

**REQ-APP-06:** New descendants, regenerated artifacts and later edits are not covered by an earlier approval. Changing a child creates a draft, marks the current parent bundle as requiring renewed approval, and preserves the old approved baseline. Reapproving the parent approves its new version manifest.

**REQ-APP-07:** Rejection and revocation affect the selected versions and inherited approval scope; independently approved versions are evaluated separately. Neither approval nor revocation changes completion status in delivery tools.

**REQ-APP-08:** Publication is a separate permission and action. Only approved, non-revoked versions may be sent outward. Previously published items are not deleted automatically when approval is revoked; raise a reconciliation task.

### 10.3 Baselines and Change Requests

Create named immutable scope, estimate, schedule and rate snapshots. Compare additions, removals and changed values against a baseline. A change request shall capture reason, evidence, affected artifacts, effort/cost/date impact and decision. Dashboards shall let users select original baseline, current approved plan and latest forecast independently.

## 11. Estimation and Costing

### 11.1 Estimate Representation

Each estimate shall record method, estimator, date, source versions, assumptions, low/likely/high values, confidence label and role breakdown. Support discovery spikes and unknown values; zero shall not represent missing estimates.

Story points are team-relative complexity measures. Person-hours are labor effort. Person-days are derived using the project day length, proposed default eight working hours. Calendar duration depends on allocation, working days and dependencies. There shall be no universal story-point-to-hour conversion.

At project start, AI uses explicit scope, complexity and role templates to propose estimates. Estimates are not commitments until reviewed. Use independently editable point and effort values with inconsistency warnings rather than forced equivalence.

### 11.2 Hierarchy Aggregation

Epics and features shall receive independent rough estimates before decomposition. Once children are estimated, their rollup becomes the detailed forecast. Preserve the initial parent rough estimate for comparison; do not add it again to child totals.

Allow explicit parent-level overhead work through separate overhead entries, clearly excluded from child estimates. Sum comparable team story points only; multi-team totals shall be labeled non-comparable unless a validated normalization is configured. Maintain range totals and assumptions; sums of bounds shall not be presented as statistical confidence intervals.

### 11.3 Formulas

- Role effort: `person_hours[r]`.
- Total effort: `sum(person_hours[r]) + explicit_overhead_hours`.
- Person-days: `total_person_hours / project_hours_per_person_day`.
- Estimated labor cost: `sum(person_hours[r] × effective_hourly_rate[r])`.
- Actual labor cost: `sum(approved_time_entry_hours × rate_effective_on_work_date)`.
- Remaining forecast: approved or reviewed remaining effort, independent of hours already consumed.
- Forecast at completion: actual effort/cost to date plus forecast remaining effort/cost.
- Available capacity: scheduled working hours less leave/non-project commitments, multiplied by allocation and an explicitly configured focus factor.

Rate cards shall be effective-dated, currency-aware and permission-restricted. Include optional non-labor costs and contingency as separate lines. Do not combine currencies without an explicit exchange-rate snapshot. Do not double apply focus reductions when allocations already represent productive hours. Validate cumulative staff allocations across projects and warn above configured capacity.

### 11.4 Learning from Delivery Data

Capture approved initial/revised estimates, role mix, scope attributes, team, actual time, completion date, rework and scope-change markers. Use only complete, consented company data; exclude canceled or incomplete work from straightforward completed-work calibration.

Start with transparent rule-based ratios and similarity retrieval. Proposed minimum for a cohort adjustment: 30 usable completed stories; otherwise show insufficient evidence and use templates. Report cohort size, missing timesheet data and outliers. Compare predicted versus actual effort using error metrics suitable for positive effort and track interval coverage.

Train or recalibrate in a controlled offline job, evaluate on a time-separated holdout and require administrator approval before activation. Keep versioned models/rules, rollback and per-project opt-out. Improvement is an objective to measure, not a guaranteed outcome. Never overwrite old estimates or learn from story points as if they were actual time.

## 12. Scrum, Kanban and Project Monitoring

**REQ-PLAN-01:** Support releases, milestones, sprint calendars, sprint goals, backlog prioritization and sprint capacity planning.

**REQ-PLAN-02:** Support Kanban columns, workflow mapping, WIP limits, blocked reasons, aging and service classes.

**REQ-PLAN-03:** Maintain working calendars, holidays, leave, role skills, allocations and actual time entry with approval/correction audit.

**REQ-PLAN-04:** Detect dependency cycles, unowned dependencies and projected capacity overload. Show configurable what-if forecasts without altering the approved plan.

**REQ-PLAN-05:** Track execution status separately from artifact approval, client acceptance and connector health.

Required charts:

| Chart | Required behavior |
|---|---|
| Planned versus actual effort | Baseline, current forecast, actual and remaining; filters by period, role, team and hierarchy |
| Cost/budget comparison | Baseline budget, actual and forecast-at-completion; internal access by default |
| Scrum burndown / burnup | Selected point or effort unit, scope changes and completed work; no mixing of units |
| Velocity | Completed points by sprint for a specific team; show insufficient-history state |
| Kanban cumulative flow | Status history, WIP and bottlenecks |
| Cycle/lead time and aging | Explicit start/end policies and working/calendar-time selection |
| Capacity and allocation | Available capacity versus planned effort by role/person and period |
| Milestones/dependencies | Schedule view with current forecast and baseline dates |
| Quality and scope | Requirement/test coverage, pending approvals, unresolved questions and scope changes |

Store daily snapshots and status transition history. Charts shall expose metric definitions, units, filters, as-of time and data freshness. Completion percentage, where shown, uses an explicitly selected weighting policy; “Done” status alone shall not imply passed tests. Forecast methods shall disclose data sufficiency and assumptions.

## 13. Tests and Project Testbook

For each story, generate descriptive test cases and equivalent or linked Gherkin scenarios. Each case shall include ID, title, story/criterion links, objective, test type, priority, preconditions, synthetic data, steps, expected results, environment assumptions and review state.

Cover positive, negative, boundary, validation, permissions, integration and applicable NFR cases. Include cross-story end-to-end suites and parent-level acceptance tests. A coverage matrix shall flag criteria with no tests and tests with no linked requirement.

Gherkin requirements:

- Feature, Scenario/Scenario Outline, Given/When/Then, optional Background and Examples.
- Stable tags for requirement, story, acceptance criterion, priority and test category.
- Configurable English or Greek supported dialect; parse/validate using the selected parser dialect.
- Observable business behavior with explicit expected results, avoiding invented implementation details.
- Examples with synthetic data and no secrets.
- Store canonical scenario structures so translated display versions do not create duplicate tests.

Example:

```gherkin
@STORY-042 @AC-042-02 @negative @high
Feature: Restricted project access
  Scenario: Client cannot access an unshared project
    Given an authenticated client reviewer with access only to Project A
    When the reviewer requests an artifact from Project B
    Then access is denied
    And no Project B content is returned
```

The testbook shall contain purpose, release/version manifest, assumptions, environments, entry/exit criteria, suites, descriptive cases, Gherkin, coverage and unresolved gaps. Generation shall not label tests Passed. A later manual execution module may record run status, evidence and defects separately.

## 14. Bidirectional Integrations

### 14.1 Connector Capability Discovery

Connectors shall discover accessible projects, item types, fields, workflow transitions, identity mappings and hierarchy capabilities before configuration. Present a compatibility report and require mapping approval. All three requested tools remain in target scope; deliver adapters incrementally.

| Canonical element | Jira proposal | Azure DevOps proposal | Asana proposal |
|---|---|---|---|
| Epic | Configured epic type | Epic where supported by project process | Configured task/container with canonical type metadata |
| Feature | Configured type/link strategy; do not assume an extra native level | Feature where supported | Task/subtask or linked grouping with metadata |
| Story | Configured standard issue type | User Story for Agile; Product Backlog Item for Scrum; discover actual type | Task/subtask with canonical type field |
| Criteria/tests | Mapped fields, description or explicitly configured linked artifacts | Mapped fields/linked artifacts where supported | Structured description or permitted custom fields/linked references |
| Points/effort | Discovered point/time/custom fields | Discovered process-specific fields | Permitted custom fields or explicit structured fallback |

These are implementation mappings, not claims of equivalent native hierarchies. Unsupported fields remain in the internal canonical model and are shown in the publication preview. Never silently flatten hierarchy or claim a successful round trip when information was lost.

### 14.2 Synchronization Contract

- Synchronize status, assignee, estimates, hierarchy, selected content and approved comments according to field-level rules.
- Internal approved artifact versions are authoritative for generated specifications. External tools are proposed authorities for operational status/assignee and actual worklogs when supported. Estimates use three-way comparison and conflicts by default.
- Incoming operational status/assignment changes may update delivery state immediately. Incoming specification, criteria or material estimate changes create a reviewable draft/change request and do not inherit approval.
- Maintain internal UUID ↔ external item ID mappings for each destination, sync revision, last payload hash and last common field values.
- Use approved publication manifests, transactional outbox jobs, idempotency keys, webhook deduplication, retries with backoff, dead-letter handling and scheduled reconciliation.
- Verify webhook authenticity using each provider's supported mechanism. Keep webhook receivers narrowly exposed; otherwise use polling for company-hosted deployments.
- Prevent loops using origin markers, content comparison and revision metadata. Do not rely solely on timestamps.
- Resolve concurrent changes through a field-level conflict view; no silent last-write-wins for estimates or approved requirements.
- Respect remote permissions, mandatory fields, API rate limits and allowed transitions. Missing identities create a mapping task rather than silently reassigning.
- Deletions become tombstones/reconciliation tasks by default; automatic hard deletion is disabled.
- Show per-item success, pending, conflict and failure. A partial remote batch cannot be treated as an atomic successful publication.
- Support one primary delivery destination per project initially; multiple destinations require explicit field ownership and routing to avoid cross-tool feedback loops.
- Synchronize worklogs only where supported; identify entries by origin and external ID to prevent duplicate actual effort.
- Credentials shall remain encrypted on company infrastructure and shall never enter AI context.

## 15. Client Collaboration

Publish a selected version snapshot to a client workspace with approved artifacts, designs, questions and selected progress reports. Separate internal and client comments. Allow feedback, requested changes and optional client acceptance per artifact or bundle.

Sharing shall default to immutable approved versions. Draft sharing requires an explicit project permission and visible draft label. Source files, recordings, internal risk notes, financial rates and AI diagnostics are excluded unless deliberately allowed. Source access is granted separately from derived artifact access.

Provide expiry, revocation, download restrictions where feasible and an access audit. Enforce the same policies for notifications, search snippets, exports and shared report templates. Notifications shall not contain confidential body text by default.

## 16. Report Builder and Exports

**REQ-REPORT-01:** Allow users to choose authorized datasets, fields, filters, grouping, sorting, date range, aggregation, baseline and chart types through a visual builder.

**REQ-REPORT-02:** Provide templates for backlog, estimates by role, planned/actual effort, cost forecast, capacity, sprint progress, Kanban flow, traceability, testbook, approval history, change impact and connector health.

**REQ-REPORT-03:** Save private/project templates and parameterized views. Report queries shall use a validated allowlist, not arbitrary database commands or client-provided code.

**REQ-REPORT-04:** Export .xlsx, explicitly requested .xls, and versioned JSON. Preserve stable IDs and parent/child references; generate multiple sheets for normalized entities and separate summary sheets.

**REQ-REPORT-05:** Legacy .xls exports must enforce their format limits, including 65,536 rows and 256 columns per sheet; split output or recommend .xlsx, never silently truncate. Escape formula-like user text in spreadsheet exports while preserving real numeric types.

**REQ-REPORT-06:** JSON exports shall include schemaVersion, generatedAt, projectId, filters, selected baseline, timezone, currency/unit definitions, entities and relation records. Large exports may use a ZIP of JSON files with a manifest.

**REQ-REPORT-07:** Export from an identified consistent snapshot so totals and detail rows agree. Record row counts, warnings, schema version and applied permissions. A report snapshot is not an importable full backup unless explicitly designed as one.

**REQ-REPORT-08:** Apply client column restrictions server-side, including fields derived from hidden costs. Saved templates cannot grant additional permissions. Support asynchronous large exports, progress and expiring download links.

Example report envelope:

```json
{
  "schemaVersion": "1.0",
  "generatedAt": "2026-10-01T08:00:00Z",
  "projectId": "project-001",
  "baselineId": "baseline-001",
  "timezone": "Europe/Athens",
  "units": {"effort": "person_hours", "hoursPerPersonDay": 8},
  "currency": "EUR",
  "filters": {"approvalState": "approved"},
  "items": [{"id": "story-001", "parentId": "feature-001", "version": 3,
    "type": "story", "storyPoints": 5, "effortHours": 24, "effortDays": 3}],
  "warnings": []
}
```

## 17. Proposed Technical Architecture

### 17.1 Components

| Component | Proposed responsibility |
|---|---|
| React + TypeScript web application | Analyst workspace, approval bundles, dashboards, reporting and client portal |
| TypeScript backend (e.g. NestJS) | Authentication, project APIs, policy enforcement, versioning, approval and synchronization |
| Python AI workers | Local transcription/OCR, evidence extraction, role orchestration and evaluation |
| MongoDB | Primary NoSQL records, immutable versions, relationships, policy configuration and job metadata |
| Company-hosted object storage | Originals, recordings, exports and large generated files |
| Company-hosted vector index | Permission-scoped semantic retrieval; derived index, rebuildable from authoritative sources |
| Durable queue and workers | Ingestion, AI jobs, exports, sync and scheduled calibration |
| AI gateway | Model routing, egress policy, redaction, budgets and local/cloud adapters |
| Integration adapters | Provider discovery, mapping, webhooks/polling and reconciliation |
| Reverse proxy / identity service | TLS, routing and SSO integration |

Component names are proposals. Select maintained products, compatible licenses and pinned versions during implementation. A separate vector service is optional if the selected company-hosted database deployment supports the required retrieval. Object storage and backups must be company controlled; a hosted database/vector default must not silently violate residency.

### 17.2 Docker Deployment

Provide Docker Compose for an initial company-hosted environment with frontend, API, workers, MongoDB, object store, queue, optional vector service and optional local inference/transcription services. Use a MongoDB replica-set configuration where transactional semantics are required. A single-host installation is not high availability.

Deliver environment templates, persistent volumes, health/readiness checks, non-root containers where supported, resource limits, secrets injection, versioned migrations and installation/upgrade/rollback instructions. Separate development and production configurations. Do not publish database, object store or inference ports publicly.

CPU local mode shall be supported at reduced throughput; GPU acceleration is optional. Model-specific RAM/VRAM and processing throughput shall be benchmarked before hardware procurement. Model weights, API credentials and client data shall not be embedded in images.

### 17.3 API Outline

All endpoints are proposed versioned REST operations under `/api/v1`, with server-side authorization, pagination, structured errors and optimistic concurrency where relevant.

| Resource | Example operations |
|---|---|
| Projects/members | Create/update project, assign roles, set policy and calendar |
| Sources | Create upload session, finalize, inspect extraction, correct transcript, version and archive |
| Analysis jobs | Start a scoped run, inspect stages/findings, cancel and resume |
| Requirements/items | CRUD drafts, links, history, estimate updates and diffs |
| Approvals | Preview manifest, submit decision with expected version, revoke |
| Baselines/changes | Create baseline, compare, evaluate and decide change requests |
| Tests/testbooks | Generate, edit, validate Gherkin, assemble versioned book |
| Planning/time | Sprints, capacity, allocations, worklogs and metric queries |
| Connectors | Discover, configure mapping, preview publication, enqueue sync and resolve conflicts |
| Sharing | Create/revoke scoped grant, review comments and client acceptance |
| Reports | Save definition, preview, start export and retrieve authorized results |

Mutating long-running operations shall accept an idempotency key and return a job ID. Enforce upload limits and quotas server-side. API documents shall specify error codes for authorization, version conflicts, invalid mappings and policy-blocked egress.

## 18. NoSQL Data Model

Use bounded document aggregates and reference large/many-to-many collections. Never embed an unbounded project backlog, transcript or audit log in a single document.

| Collection/entity | Important fields |
|---|---|
| projects | ID, client, members/policy refs, languages, method, calendar, currency, day length |
| sourceDocuments / sourceVersions | Object refs, hashes, classification, status, extractor version |
| sourceChunks | Version ref, locator, normalized text, access scope, embedding ref |
| requirements / requirementVersions | Type, wording, priority, sources, assumptions and decisions |
| backlogItems / artifactVersions | Stable ID, type, parent, version, description, criteria refs, state |
| evidenceLinks / dependencyLinks | Source/target IDs and versions, relation type, rationale |
| estimates / rateCards | Item version, role hours, ranges, points, rates and effective dates |
| testCases / testVersions | Criterion links, steps, expected outcomes and structured Gherkin |
| analysisJobs / reviewFindings | Stage, input manifest, outputs, model/prompt versions, findings |
| approvalEvents / approvalManifests | Approver, root, included versions, inheritance, waivers |
| baselines / changeRequests | Immutable manifests, snapshots, decisions and impact |
| iterations / allocations / worklogs | Team, dates, role/person, effort, origin and approval |
| statusEvents / metricSnapshots | Transitions, as-of values, methodology and baseline refs |
| integrations / externalMappings | Destination, secret reference, field rules, IDs, common state |
| syncEvents / outboxJobs | Event IDs, payload refs, retries, conflict and dead-letter state |
| shareGrants / comments | Audience, artifact versions, expiry, visibility and acceptance |
| reportDefinitions / exportJobs | Authorized query, parameters, snapshot and object reference |
| auditEvents / calibrationVersions | Actor/action, object versions, evaluation and activation |

Use schema validation, project-scoped indexes, compound uniqueness for external mappings and idempotency keys, and optimistic concurrency for version writes. Enforce hierarchy integrity and dependency-cycle rules at the application layer. Store UTC timestamps and user/project timezones separately; use decimal-safe money representation with currency. Retain immutable evidence needed for historical approvals subject to configured retention policy.

## 19. Non-Functional Requirements

The following are proposed acceptance targets to validate on an agreed reference deployment.

| ID | Requirement and verification |
|---|---|
| NFR-01 | No cross-project/client data leakage through API, retrieval, exports or jobs; verify with negative authorization tests |
| NFR-02 | Local-only policy produces no project-derived outbound cloud requests; verify with egress capture and cloud-fallback failure tests |
| NFR-03 | TLS in transit and encrypted persistent storage/backups; keys and secrets separated from content |
| NFR-04 | P95 ordinary interactive API responses below 2 seconds at 50 concurrent active users on a 10,000-story reference project; exclude AI/import/export jobs and test separately |
| NFR-05 | All long-running work is queued, observable and restartable without duplicate approved artifacts or remote items |
| NFR-06 | Proposed service availability objective 99.5% monthly; measured for the agreed deployment, with maintenance policy explicitly defined |
| NFR-07 | Proposed RPO ≤24 hours and RTO ≤8 hours for initial deployment; prove through restore drills rather than backup-job success alone |
| NFR-08 | All generated claims requiring evidence resolve to valid locators or are labeled assumptions; assess with a curated Greek/English evaluation set |
| NFR-09 | All Gherkin and API outputs pass applicable structural validation before approval; semantic quality still requires review |
| NFR-10 | Responsive desktop-first interface, keyboard access and accessible charts/tables; target WCAG 2.2 AA with an implementation accessibility review |
| NFR-11 | Structured logs/metrics/traces use correlation IDs and exclude raw recordings, document text, secrets and confidential prompts by default |
| NFR-12 | Graceful cloud/connector outage handling with visible stale-data timestamps and no policy-breaking fallback |
| NFR-13 | Configurable retention, archive and deletion workflow covers originals, derivatives, vectors, caches and exports; backups expire according to documented policy |
| NFR-14 | Unicode Greek/English round trip through ingestion, search, Gherkin and Excel/JSON export; validate mixed-language fixtures |

Retention, recording notice/consent and client data-handling procedures shall be configured under company policy. They are operational requirements, not a claim that the software alone establishes regulatory compliance.

## 20. Application Screens

1. Project portfolio: health, milestones, budget visibility and pending decisions.
2. Project setup: members, delivery method, language, calendar, rates and AI/data policy.
3. Evidence workspace: uploads, revisions, extraction and timestamp-linked transcript editor.
4. Analysis workspace: role stages, findings, questions, source-backed proposals and rerun controls.
5. Backlog tree: epic/feature/story detail, criteria, tests, dependencies and estimate rollups.
6. Specification workspace: functional/NFR content, diagrams, data/API models and version comparison.
7. Approval inbox: subtree manifest, diff, blockers, waivers and inherited-approval preview.
8. Planning workspace: sprints, Kanban, allocation, capacity and milestones.
9. Testbook workspace: cases, Gherkin, coverage and versioned assembly.
10. Project dashboards: effort, cost, flow, quality and scope with drill-down.
11. Report builder: dataset/field selection, filters, preview and exports.
12. Integration console: discovery, mappings, publication previews, failures and conflicts.
13. Client workspace: selected artifacts, comments, questions and optional acceptance.
14. Administration: identity, models, storage, retention, budgets, audits and calibration.

## 21. System Acceptance Scenarios

| ID | Scenario | Required result |
|---|---|---|
| AT-01 | Greek meeting audio + English brief + Excel schedule are ingested | Correct project association, source versions and navigable evidence locators; uncertainty remains visible |
| AT-02 | BA output contains an unsupported technical assumption | Technical review labels it and QA evaluates testability; no invented confirmation |
| AT-03 | Epic has two features, five stories and linked tests | One human approval approves the exact descendant manifest with inherited event references |
| AT-04 | Story changes while parent approval is being submitted | Approval fails atomically with a version conflict; no partial approvals |
| AT-05 | A new story is added after epic approval | New story remains draft and parent current bundle requires renewed approval |
| AT-06 | A local-only job cannot reach its local model | Job fails/pauses visibly; no project content is sent to cloud |
| AT-07 | Confidential job attempts to send a restricted excerpt | Egress gate blocks the payload and records a policy event |
| AT-08 | Same publication job/webhook is replayed | No duplicate external item, worklog or repeated update loop |
| AT-09 | External estimate and local estimate both change | Three-way conflict is visible; approved baseline remains intact |
| AT-10 | External status changes while specification remains approved | Delivery state updates without changing artifact approval or falsely marking tests Passed |
| AT-11 | Client requests internal cost report or unrelated source | Server denies access and returns no sensitive content |
| AT-12 | Parent rough estimate is 100h and children total 80h | Detailed rollup is 80h plus explicit overhead; initial 100h remains a comparison value |
| AT-13 | Report exports filtered hierarchy to Excel and JSON | Matching totals/IDs, documented units, Unicode and permission-filtered fields |
| AT-14 | .xls report exceeds sheet limits | Output splits with a clear manifest or offers .xlsx; no silent truncation |
| AT-15 | Source revision changes a validation rule | Impact report identifies linked criteria, stories and tests needing review |
| AT-16 | No historical estimates exist | Template estimates with uncertainty are shown; no unsupported learned-accuracy claim |
| AT-17 | Calibration candidate fails holdout evaluation | Candidate stays inactive and prior method remains available |
| AT-18 | Deployment is restored from backup | Source/version/approval links and external mappings remain coherent; vector index can be rebuilt |
| AT-19 | Gherkin has a missing Examples value or invalid syntax | Validation blocks approval or records a required correction |
| AT-20 | Design is only a static screenshot | UI observations are extracted; missing interaction/business behavior is raised as questions |

## 22. Delivery Plan

No dates or effort commitments are asserted until the delivery team, connector environments and local AI hardware are known.

### Phase 0 — Feasibility and Design

Validate actual Jira/Azure/Asana hierarchies and permissions, sample Figma/XD assets, Greek transcription, company egress requirements and CPU/GPU throughput. Confirm identity, retention, reference load and provider contracts. Produce architecture decisions, schemas and a working vertical-slice demo.

### Phase 1 — Core Analysis and Approval

Company Docker deployment, NoSQL storage, users/projects, uploads, local transcription/extraction, bilingual retrieval, sequential analyst workflow, backlog, criteria, tests, basic specifications and version-bound cascade approvals. Include source traceability and local-only enforcement from the start.

### Phase 2 — Delivery and Integration

Connector adapter framework, one agreed priority connector followed by the other two, bidirectional conflict handling, baselines, worklogs, rate cards, Scrum/Kanban capacity and core charts. Establish automated reconciliation and operational failure handling.

### Phase 3 — Client and Reporting

Controlled client sharing, client feedback/acceptance, advanced specifications, project testbook assembly, report builder, .xlsx/.xls/JSON exports and full change-impact workflows. Basic exports should already exist in earlier phases for reviewability.

### Phase 4 — Calibration and Optional Extensions

Historical calibration with evaluation/rollback; richer forecasts, multiple-destination routing, optional manual test execution, more source connectors and advanced design extraction.

Every phase shall include appropriate security, authorization, integration and recovery verification. Required features are not removed merely because they are scheduled later.

## 23. Risks and Implementation Decisions

| Risk | Required response |
|---|---|
| Confidential content reaching cloud | Default-deny classification gate, local processing and documented payload disclosure |
| AI hallucinations or stale evidence | Citations, assumption labels, version manifests, quality gates and human approval |
| Parent approval hides weak descendants | Complete preview, blocker/waiver handling and atomic version-bound cascade |
| Cross-tool hierarchy differences | Discover capabilities and show explicit fallback mappings |
| Native XD extraction uncertainty | Export-based baseline support and feasibility gate for native parsing |
| Greek transcription errors | Representative audio evaluation and editable timestamp-linked transcript |
| Incomplete actual-time data biases estimates | Data completeness indicators, cohort filters and conservative calibration |
| Remote changes overwrite scope | Separate operational state and approved content; reviewable drafts and conflicts |
| Large document/AI processing cost | Queues, budgets, cancellation, selective generation and incremental processing |
| Client export leaks financial context | Server-side field restrictions and derived-metric policy checks |

Remaining configuration decisions have proposed defaults rather than blocking specification: exact stack/products; priority connector; company identity provider; local model hardware; permitted cloud disclosure; desired day length; available rate cards; client acceptance authority; and final capacity/performance targets.

## 24. Reference Documentation

These official references support integration discovery and the need for provider-specific mappings. Validate API versions, licensing and actual tenant capabilities at implementation time; this document does not freeze third-party behavior.

- Jira Cloud issue types and hierarchy metadata: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-types/
- Jira Cloud REST API: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
- Azure Boards work items and process-dependent types: https://learn.microsoft.com/en-us/azure/devops/boards/work-items/about-work-items?view=azure-devops
- Azure Boards features and epics: https://learn.microsoft.com/en-us/azure/devops/boards/backlogs/define-features-epics?view=azure-devops
- Asana webhook guidance: https://developers.asana.com/docs/webhooks-guide

## 25. Definition of Done

The target application is complete when all confirmed capabilities and required acceptance scenarios pass on the agreed deployment; all three connectors have validated mappings and conflict handling; approved hierarchical bundles cannot be mutated silently; company data-residency rules are enforced; clients see only granted versions and fields; exports match report snapshots; and installation, recovery, administration, model-policy and user documentation are delivered.
