# Automated test suite

Six layers, one entry point. The first four need no infrastructure at all; the
last two run against a deployment you start.

```bash
scripts/run-tests.sh            # unit + API + acceptance + frontend (no infrastructure)
scripts/run-tests.sh --all      # the above, then the live deployment suites
scripts/run-tests.sh --e2e      # only the live deployment suites
scripts/run-tests.sh --coverage # with coverage reports
```

On Windows PowerShell: `.\scripts\run-tests.ps1 [-All] [-E2E] [-Coverage]`.

For the live layers, start a deployment first:

```bash
docker compose up -d
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm seed
```

---

## The layers

| Layer | Where | Count | What it proves | Infrastructure |
|---|---|---|---|---|
| Service level (unit) | `backend/tests/unit` | 68 | A service's rules are right in isolation: estimation formulas, the approval cascade, Gherkin, exports, the egress gate, connector conflict handling | none |
| API functional | `backend/tests/api` | 133 | The real application over HTTP: routing, authentication, authorization, serialisation, error codes, every workspace endpoint | none |
| Acceptance scenarios | `backend/tests/acceptance` | 20 | The specification's section 21 scenarios, AT-01 to AT-20, one test each | none |
| Frontend unit and component | `frontend/src/__tests__` | 81 | The API client, chart primitives, interface primitives (including dialog, tab and table keyboard behaviour), internationalisation and three pages against a stubbed API | none |
| Live API end to end | `backend/tests/e2e` | 11 | The running stack: real replica set, real worker, real web tier | a deployment |
| Browser end to end | `frontend/e2e` | 84 | The real browser journey through the workspaces, a WCAG 2.1 AA axe scan of every screen in the light and dark themes, phone layouts at 375px and 320px, and the theme choice | a deployment |

**397 automated checks in total: 302 of them need no infrastructure.**

The in memory database substitute (`mongomock_motor`) backs the first three
layers, so a full functional run takes about four minutes and needs nothing but
Python. The live layers then confirm the parts a substitute cannot: transactional
commits on a replica set, the worker consuming its queue, nginx routing, and the
browser.

---

## Layer one — service level

`backend/tests/unit`. Builds domain objects directly through the repositories and
calls one service. Fixtures live in `tests/unit/conftest.py`.

Covers the rules that are easy to get subtly wrong: the estimation formulas and
the rule that a parent's rough estimate never joins the child rollup; the
approval manifest and its blockers; Gherkin parsing, validation and bilingual
rendering; the `.xls` row and column limits; the egress gate's deny decisions;
three way connector conflicts.

## Layer two — API functional

`backend/tests/api`. Drives the real FastAPI application through an ASGI
transport, so a test exercises the same routing, dependency injection,
authorization and error mapping a browser would hit.

Fixtures (`tests/support.py`) give you signed in actors — `lead`, `admin`,
`reviewer`, `outsider` — and composable helpers:

```python
async def test_something(lead, project):
    response = await lead.post(f"/projects/{project['id']}/backlog/items",
                               json={"type": "epic", "title": "Accounts"})
    assert response.status_code == 201
```

| Module | Covers |
|---|---|
| `test_auth_and_authorization.py` | Sign in, token handling, the role to permission matrix, project isolation, revoked and expired membership, error structure |
| `test_evidence.py` | Upload limits, every extractor path, failure reporting, versions and impact, transcripts, restricted sources, bilingual search |
| `test_analysis_and_backlog.py` | The analyst stages (including the optional UX and data analysts) and the per project choice of analysts, findings and questions, hierarchy rules, versioning, optimistic concurrency, estimates and rollups, dependency cycles |
| `test_approvals_and_planning.py` | Manifest preview, cascade, stale hash, blockers and waivers, revocation, baselines, change requests, board, capacity, time, charts |
| `test_testing_reports_sharing.py` | Gherkin validation and dialects, coverage, testbook assembly, report permissions, export formats, share grants, client workspace, administration |
| `test_superuser_and_manual_entry.py` | The platform owner's standing, its audit trail and its limits; authoring a requirement, question, glossary term, specification, evidence link, test case, sprint, milestone, allocation and rate card by hand |

## Layer three — acceptance scenarios

`backend/tests/acceptance/test_system_acceptance.py`. One test per numbered
scenario in specification section 21, named `test_at01_…` to `test_at20_…`, so a
reviewer can read the specification and the suite side by side.

```bash
cd backend && pytest -m acceptance -v
```

| Scenario | Test asserts |
|---|---|
| AT-01 | Greek transcript, English brief and a spreadsheet land with paragraph, row and timestamp locators; uncertainty stays visible |
| AT-02 | Generated content is labelled a proposal; nothing is presented as a confirmed client decision |
| AT-03 | One approval covers 1 explicit and 12 inherited versions, each referencing the parent event |
| AT-04 | A change between preview and submission fails with `version_conflict` and approves nothing |
| AT-05 | A story added after approval stays draft and the parent needs renewal |
| AT-06 | An unreachable local model pauses the job visibly and writes no outbound manifest |
| AT-07 | A restricted excerpt is blocked, recorded by category, and never stored in the log |
| AT-08 | A replayed publication and a replayed webhook create no duplicates |
| AT-09 | Both sides moving an estimate produces a three way conflict; the baseline is intact |
| AT-10 | An external status change updates delivery state, not approval, and marks no test passed |
| AT-11 | A client is refused cost, sources and rate cards, and the response carries no content |
| AT-12 | Parent rough 100h versus children 80h plus 12h overhead: rollup 92h, 100h kept for comparison |
| AT-13 | Excel and JSON agree on rows and ids; units, currency and Greek text survive |
| AT-14 | A 65,546 row `.xls` splits with a manifest; no row is dropped |
| AT-15 | A revised source produces an impact report and marks linked items stale |
| AT-16 | Without history, estimates are template proposals and calibration reports insufficient evidence |
| AT-17 | A candidate that does not beat the current method cannot be activated |
| AT-18 | After a simulated restore, approval and evidence links resolve and the index rebuilds |
| AT-19 | A missing Examples value and invalid syntax both block the artifact |
| AT-20 | A screenshot yields no invented behaviour; the OCR gap is reported |

## Layer four — frontend unit and component

`frontend/src/__tests__`, run with Vitest and Testing Library.

* `api.test.ts` — bearer token handling, query building, idempotency header,
  multipart uploads, the error to `ApiError` mapping including version conflict
  and policy blocked, the 401 path, unavailable storage.
* `components.test.tsx` — categorical colours assigned in fixed order and never
  cycled, the chart frame's definition and units, the values table, the
  insufficient data state, mark geometry (2px lines, 4px rounded bar ends, ring
  on markers), state and provenance badges, error banner, tabs, Greek and
  English switching.
* `pages.test.tsx` — portfolio health, the approval modal (blockers, waivers, the
  non waivable case, the version conflict message) and the client workspace,
  each against a stubbed API.
* `report-chart.test.tsx` — the report aggregation (sum, count, average, minimum,
  maximum, a second dimension, a folded tail, non numeric values) and the chart
  surface it feeds.

```bash
cd frontend && npm run test            # once
cd frontend && npm run test:watch      # while developing
cd frontend && npm run test:coverage   # with a coverage report
```

## Layer five — live deployment

`backend/tests/e2e/test_live_deployment.py` is skipped unless
`AIT_E2E_BASE_URL` is set, so it never fails a developer who has no stack
running.

```bash
cd backend
AIT_E2E_BASE_URL=http://localhost:8080 pytest tests/e2e -q
```

It checks liveness and readiness through the published surface, that the web tier
serves the application and proxies the API, the approval cascade and its conflict
path against a real replica set, client isolation, charts and reports, an export
round trip through storage, that the worker actually consumes a queued job, and
that the audit trail was written.

## Layer six — browser

`frontend/e2e/workspaces.spec.ts`, run with Playwright against the same
deployment.

```bash
cd frontend && npx playwright test
cd frontend && npx playwright test --ui      # interactive
cd frontend && npx playwright show-report    # after a failure
```

`workspaces.spec.ts` walks sign in (including a rejected password and the Greek
interface), each analyst workspace, the approval bundle with waivers and
revocation, the client reviewer's restricted view, and checks the layout does not
overflow at 420px.

`entry-and-ownership.spec.ts` authors each kind of entry by hand through the real
forms, charts a report, and signs in as the platform owner to confirm the whole
estate and the administration screen are reachable. Each test stamps its entries
with a unique suffix so repeated runs stay independent.

`accessibility.spec.ts` scans every screen with axe-core against the WCAG 2.1
A and AA rules (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`): sign in (also with an
error shown), the portfolio, each of the twelve project workspaces, every tab of
a tabbed workspace, an open dialog, the Greek interface, administration and the
client workspace, once in the light theme and once in the dark theme. A failure lists each violated rule with its impact, the
offending elements and a link to the rule's guidance.

```bash
cd frontend && npx playwright test e2e/accessibility.spec.ts
```

`theme.spec.ts` checks that the interface follows the operating system's light
or dark preference until someone picks a theme, that a picked theme overrides it
and survives a reload, and that the stored theme is applied before the first
paint so a dark theme never flashes light.

`mobile.spec.ts` loads every screen at 375px and 320px and fails if the page
scrolls sideways (wide data tables may scroll inside their own card). It also
checks that an item dialog fits the screen, that the navigation folds behind the
Menu button and closes after a choice or on Escape, and that form fields use a
16px font so iOS does not zoom on focus.

Automated rules catch only part of WCAG. Before a release, also check by hand:
keyboard only use of a full journey, a screen reader pass (NVDA or Narrator),
400% zoom at 1280px width, and that names and headings make sense in context.

Traces and screenshots are retained on failure.

---

## Continuous integration

`.github/workflows/ci.yml` runs three jobs:

1. **backend** — unit, API and acceptance, with a coverage report as an artifact.
2. **frontend** — type check, unit tests, production build.
3. **end-to-end** — builds and starts the Docker deployment, seeds it, then runs
   the live API and browser suites. On failure it uploads the deployment logs,
   the Playwright report and the traces.

## Conventions

* **Name the behaviour, not the function.** `test_a_new_story_is_not_covered_by_an_earlier_approval`, not `test_create_story_2`.
* **Assert the promise, not the implementation.** Tests check that nothing is
  approved after a conflict, not which query ran.
* **No sleeping on timing.** The only waits are the live worker poll and
  Playwright's own auto waiting.
* **Each test owns its data.** Every test gets a fresh in memory database; the
  live suites restore what they change (the browser suite revokes the approval it
  creates).
* **A skipped test says why.** The live suites skip with the reason and the
  command that would enable them.

## Adding a test

| What changed | Where the test goes |
|---|---|
| A service rule or a formula | `backend/tests/unit` |
| An endpoint, a permission, an error code | `backend/tests/api` |
| A specification acceptance scenario | `backend/tests/acceptance` |
| A component, a chart, a page behaviour | `frontend/src/__tests__` |
| Something only a real stack shows | `backend/tests/e2e` or `frontend/e2e` |
| A new screen or a new dialog | add it to `frontend/e2e/accessibility.spec.ts` |

Markers: `acceptance`, `e2e`, `slow` (registered in `backend/pytest.ini`).
