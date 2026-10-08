# Requirements traceability

Where each numbered requirement of the specification is implemented. Paths are
relative to the repository root.

## Section 4 — Roles and authorization

| Requirement | Implementation |
|---|---|
| Role to permission matrix | `backend/app/core/policy.py` |
| Platform owner role (a deliberate addition, not in section 4) | `policy.Role.SUPERUSER`, `api/deps.project_context`; see `decisions.md` D-19 |
| Server side enforcement on every record, chunk, search, report, download, job | `backend/app/api/deps.py` + per endpoint `ctx.require(...)` |
| System administrator holds no implicit content access | `ROLE_PERMISSIONS[SYSTEM_ADMIN]`, test `test_permissions_and_sharing.py` |
| Client never sees rates, prompts, confidential evidence, internal comments | `CLIENT_FORBIDDEN_FIELDS`, `services/sharing.py`, `services/reports.py` |
| Internal approval and client acceptance are separate records | `approvalEvents` vs `backlogItems.clientAccepted` |

## Section 6 — Evidence ingestion

| Requirement | Implementation |
|---|---|
| Originals with hash, uploader, time, classification, revision | `services/sources.py: upload` |
| Isolated parsing without macros, scripts or external links | `services/extraction.py` (openpyxl `data_only`, no formula evaluation) |
| Configurable limits shown before upload | `GET /sources/limits`, `core/config.py` |
| Original and normalised text, extractor version, warnings | `SourceVersion.extractor*`, `normalizedText`, `warnings` |
| Actionable failure for protected, corrupt or unsupported files | `extraction.py` status `failed` / `needs_password` / `unsupported` |
| Duplicate and revision detection by hash | `sources.upload` content hash lookup |
| Low confidence spans marked, diarization labels correctable | `SourceChunk.lowConfidence`, `PATCH /sources/segments/{id}` |
| Meeting decisions, actions, questions extracted with timestamps | `extraction.DECISION_PATTERNS`, `parse_transcript_text` |
| Spreadsheet values flagged as cached, never silently recalculated | `_extract_xlsx` warning `cached_formula_values` |
| Inclusion, exclusion and authority ranking | `SourceDocument.excluded`, `.authority` |

## Section 7 — Knowledge and traceability

| ID | Implementation |
|---|---|
| REQ-KNOW-01 | `models/knowledge.py` glossary, questions, requirements with decisions and assumptions; each creatable by hand (`POST /requirements`, `/questions`, `/glossary`) |
| REQ-KNOW-02 | `Requirement` stable ids, type, sources, value, priority, confidence, owner, state |
| REQ-KNOW-03 | `evidenceLinks` / `dependencyLinks`, `GET /traceability`, manual linking through `POST /evidence-links` |
| REQ-KNOW-04 | `GET /sources/{id}/content` returns a restriction notice, not text |
| REQ-KNOW-05 | question register with severity, proposed clarification, owner, history |
| REQ-KNOW-06 | `Provenance` enum, `ProvenanceBadge` in the interface |
| REQ-KNOW-07 | `services/search.py` with Greek accent folding and classification filtering |
| REQ-KNOW-08 | `sources.build_impact_report`, items marked `stale`, approved history preserved |

## Section 8 — Sequential AI workflow

| Requirement | Implementation |
|---|---|
| BA → TA → QA on explicit versions | `ai/orchestrator.py: run_job` |
| Per project choice of analysts; a run cannot add one the project switched off | `models/project.py: Project.enabled_analysts`, `ai/orchestrator.py: _roles_for` |
| Optional UX analyst: personas, journeys, screen states, UX-nnn requirements | `ai/prompts.py: UX_*`, `ai/schemas.py: UXOutput`, `ai/orchestrator.py: _persist_ux` |
| Optional data analyst: quality rules, metrics, retention, migration, DATA-nnn requirements | `ai/prompts.py: DATA_*`, `ai/schemas.py: DataOutput`, `ai/orchestrator.py: _persist_data` |
| Versioned JSON schema validation before saving | `ai/schemas.py`, `gateway.run_role` |
| Role, model, config, prompt version, inputs, outputs, time, tokens, cost | `AnalysisStage.usage`, `inputManifest`, `ArtifactVersion.modelId` |
| Diffs on revision, human edits preserved, merge preview | `services/backlog.update_item`, `orchestrator.regenerate_preview` |
| Bounded correction loop, escalation instead of endless reprocessing | `orchestrator._bound_correction_loop` |
| Critical blockers enumerated | `services/approvals._blockers` |
| Waiver with rationale, visible in bundle and audit | `approvals._build_waivers`, `ApprovalEvent.waivers` |
| Architectural proposals labelled, no invented client decisions | prompts and the heuristic adapter's provenance labelling |
| Imported content is untrusted data | `ai/egress.strip_injected_instructions` |
| Checkpoints and resume | `AnalysisStage.checkpoint`, `POST /analysis/runs/{id}/resume` |
| Model routing and classification table | `ai/gateway._adapter_for`, `ai/egress.allowed_classifications` |

## Section 9 — Backlog and specifications

| Requirement | Implementation |
|---|---|
| Canonical hierarchy with validation | `models/common.ITEM_PARENT`, `backlog._validate_parent` |
| Story content contract | `models/backlog.ArtifactVersion` |
| Outcome level parent criteria | `AcceptanceCriterion.outcomeLevel` |
| Functional, NFR, diagrams, data model, API, testbook | `ai/orchestrator._persist_ta`, `services/testing.assemble_testbook`; hand authored through `POST /specifications` |
| Generated API specifications are proposals, structurally validated | `Specification.validation` note on every generated API spec |

## Section 10 — Approval, versioning, baselines

| ID | Implementation |
|---|---|
| States and immutability | `ArtifactState`, `backlog.update_item` branching |
| REQ-APP-01 | `approvals.build_manifest` subtree plus owned tests and specifications |
| REQ-APP-02 | manifest entries, counts, blockers, totals, diff, client visible subset |
| REQ-APP-03 | `reference_only` entries, `ctx.is_approver`, `APPROVER_ROLES` |
| REQ-APP-04 | `manifest_hash` including content revision, rebuild and compare on submit, `committed` flag |
| REQ-APP-05 | `ApprovalEvent.entries[].inherited`, `inheritedFromEventId`, waivers, audit record |
| REQ-APP-06 | `_mark_ancestors_for_reapproval`, new items start unapproved |
| REQ-APP-07 | `approvals.revoke` skips independently approved versions |
| REQ-APP-08 | `integrations.enqueue_publication` requires a committed, non revoked event; revocation raises a reconciliation task |
| Baselines and change requests | `services/baselines.py` |

## Section 11 — Estimation and costing

| Requirement | Implementation |
|---|---|
| Estimate representation, zero is not missing | `models/backlog.Estimate`, `unknown` and `spikeRequired` flags |
| No universal point to hour conversion | independent fields plus `inconsistency_warnings` |
| Parent rough estimate kept, not added | `estimation.rollup` |
| Explicit parent overhead | `Estimate.overheadHours` |
| Multi team points labelled non comparable | `EstimateRollup.storyPointsComparable` |
| The five formulas | `estimation.total_hours`, `person_days`, `estimate_cost`, `actual_cost`, `cost_summary` |
| Effective dated, currency aware rate cards | `models/backlog.RateCard`, `effective_rate_card` |
| No currency mixing without a snapshot | `Money.plus` refuses |
| Focus factor not applied twice | `estimation.capacity` |
| Cross project allocation warnings | `cross_project_allocation_warnings` |
| Calibration with holdout, approval, rollback, opt out | `services/calibration.py` |

## Section 12 — Delivery monitoring

| ID | Implementation |
|---|---|
| REQ-PLAN-01 to 03 | `api/v1/planning.py`, `models/planning.py` |
| REQ-PLAN-04 | `backlog.detect_dependency_cycles`, capacity rows |
| REQ-PLAN-05 | `executionStatus` separate from `state` and from client acceptance |
| Required charts | `services/metrics.py` (`planned_vs_actual`, `burndown`, `velocity`, `cumulative_flow`, `cycle_time`, `quality_scope`, `milestones`, cost) |
| Definitions, units, filters, as of time, freshness | `ChartResponse` fields, rendered by `components/charts.tsx` |
| Daily snapshots and status history | `metrics.snapshot_daily`, `statusEvents` |

## Section 13 — Tests and testbook

| Requirement | Implementation |
|---|---|
| Descriptive case contract | `models/testing.TestCase` |
| Positive, negative, boundary, permission, integration, NFR, end to end | heuristic QA role and `TestType` |
| Gherkin structure, tags, dialects, validation | `services/gherkin.py` |
| Canonical structure stored once, translations are display only | `render_feature`, test in `test_gherkin.py` |
| Coverage matrix flags both directions | `testing.coverage` |
| Generation never labels a test passed | `reviewState` stays `pending_review` |

## Section 14 — Integrations

| Requirement | Implementation |
|---|---|
| Capability discovery before configuration | `integrations/adapters/*.discover`, `CapabilityReport` |
| Mapping approval required | `Integration.mappingApproved`, re-opened when a mapping changes |
| Canonical element mapping table | adapter `suggested_type_mappings` |
| Unsupported fields stay internal and are shown | `PublicationPreviewRow.unsupportedFields` |
| Field level rules and authority | `FieldRule.ownership` |
| Outbox, idempotency, retries, dead letter, reconciliation | `services/integrations.py` |
| Webhook authenticity and deduplication | adapter `verify_webhook`, `syncEvents` unique event id |
| Loop prevention by origin marker and content comparison | `ORIGIN_MARKER`, payload hash |
| Field level conflicts, no silent last write wins | `ConflictField`, `resolve_conflict` |
| Deletions become tombstones | `allow_deletes` defaults false |
| Partial batch is not a success | `JobStatus.PARTIAL` |
| Worklogs identified by origin and external id | unique partial index on `worklogs` |
| Credentials encrypted, never in AI context | `services/secrets.py` |

## Section 15 — Client collaboration

Implemented in `services/sharing.py` and `api/v1/sharing.py`: version scoped
grants defaulting to approved versions, separate internal and client comments,
optional acceptance, expiry, revocation, an access log, and server side stripping
of internal fields.

## Section 16 — Reports and exports

| ID | Implementation |
|---|---|
| REQ-REPORT-01 | `services/reports.py` datasets, fields, filters, grouping; chart types in `frontend/src/components/report-chart.tsx` |
| REQ-REPORT-02 | `reports.templates()` covers all required templates |
| REQ-REPORT-03 | allowlisted datasets, fields and filters; no client supplied query |
| REQ-REPORT-04 | `.xlsx`, `.xls`, versioned JSON with stable ids and parent references |
| REQ-REPORT-05 | `exports.build_xls` splits at 65,536 rows and 256 columns; formula escaping |
| REQ-REPORT-06 | `exports.build_json` envelope |
| REQ-REPORT-07 | one snapshot per export, row counts, warnings, schema version, permissions |
| REQ-REPORT-08 | server side column restriction; a saved template cannot widen permissions |

## Section 19 — Non functional requirements

| ID | Where it is addressed |
|---|---|
| NFR-01 | project scoped queries everywhere, negative authorization tests |
| NFR-02 | `ai/egress.py`, local only tests |
| NFR-03 | TLS terminated by the company proxy; secrets separated from content |
| NFR-04 | indexed project scoped queries; AI and export work is queued separately |
| NFR-05 | `workers/queue.py` with idempotency, retries and stale recovery |
| NFR-06 / 07 | deployment and restore drill guidance in `operations.md` |
| NFR-08 | citations with resolvable locators; unsupported claims labelled |
| NFR-09 | Gherkin and OpenAPI structural validation before approval |
| NFR-10 | desktop first responsive layout, keyboard reachable controls, charts with legends, direct labels and a table view |
| NFR-11 | correlation ids, logs exclude content and secrets |
| NFR-12 | visible stale timestamps, no policy breaking fallback |
| NFR-13 | retention and deletion workflow documented in `operations.md` |
| NFR-14 | Greek and English round trip through ingestion, search, Gherkin and exports |
