/** Page level behaviour with a stubbed API. */
import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../i18n'
import { tokenStore } from '../lib/api'
import { ApprovalsPage } from '../pages/ApprovalsPage'
import { ClientPage } from '../pages/ClientPage'
import { PortfolioPage } from '../pages/PortfolioPage'
import { ProjectSetupPage } from '../pages/ProjectSetupPage'

type Handler = (url: string, init: RequestInit) => unknown

/** Routes a stubbed fetch by the first matching URL fragment. */
function stubApi(routes: Record<string, Handler | unknown>) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const match = Object.keys(routes).find((pattern) => url.includes(pattern))
    if (!match) {
      return new Response(JSON.stringify({ error: { code: 'not_found',
                                                    message: `no stub for ${url}` } }),
                          { status: 404 })
    }
    const route = routes[match]
    const value = typeof route === 'function' ? (route as Handler)(url, init) : route
    if (value instanceof Response) return value
    return new Response(JSON.stringify(value), {
      status: init.method === 'POST' ? 201 : 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage(element: ReactElement, { path = '/', route = '/' } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={element} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

const PROJECT = {
  projectId: 'p1', key: 'PORTAL', name: 'Customer Portal',
  clientName: 'Northwind', deliveryMethod: 'scrum',
  openCriticalQuestions: 2, pendingApprovals: 5, unresolvedFindings: 1,
  stories: 10, approvedStories: 3, estimatedHours: 124, actualHours: 40,
  budget: null, forecastCost: { amount: '12003.20', currency: 'EUR' },
  nextMilestone: 'Release 1', connectorHealth: 'not_configured', localOnly: true,
}

const MANIFEST = {
  id: 'm1', rootId: 'epic-1', rootType: 'epic', rootTitle: 'Customer accounts',
  rootVersion: 1,
  entries: [
    { itemId: 'epic-1', stableId: 'EPIC-001', itemType: 'epic', title: 'Accounts',
      version: 1, versionId: 'v1', state: 'draft', inherited: false,
      referenceOnly: false, changed: true },
    { itemId: 'story-1', stableId: 'STORY-001', itemType: 'story', title: 'Register',
      version: 1, versionId: 'v2', state: 'draft', inherited: true,
      referenceOnly: false, changed: true },
    { itemId: 'tc-9', stableId: 'TC-009', itemType: 'test_case', title: 'Other subtree',
      version: 1, versionId: 'v3', state: 'draft', inherited: true,
      referenceOnly: true, changed: false },
  ],
  counts: { epic: 1, story: 1, test_case_reference: 1 },
  blockers: [
    { kind: 'untestable_requirement', severity: 'critical',
      message: 'STORY-001 has no linked test case', targetId: 'story-1',
      targetTitle: 'Register', waivable: true },
    { kind: 'invalid_hierarchy', severity: 'critical', message: 'Not under an epic',
      targetId: 'x', waivable: false },
  ],
  diff: { added: [], removed: [], changed: [], unchangedCount: 0 },
  estimateTotals: { unit: 'person_hours', detailedHours: 24, storyPoints: 8,
                    itemsWithEstimate: 1, itemsTotal: 2 },
  clientVisibleEntries: [], manifestHash: 'hash-abc123def456',
  generatedAt: '2026-10-01T08:00:00Z',
}

beforeEach(() => {
  tokenStore.set('test-token')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('portfolio', () => {
  it('shows project health and the data policy badge', async () => {
    stubApi({ '/projects': [PROJECT] })
    renderPage(<PortfolioPage />)

    expect(await screen.findByText('PORTAL — Customer Portal')).toBeInTheDocument()
    expect(screen.getByText('Northwind · scrum')).toBeInTheDocument()
    expect(screen.getAllByText('Local only').length).toBeGreaterThan(0)
    expect(screen.getByText('Next: Release 1')).toBeInTheDocument()
    expect(screen.getByText('3/10')).toBeInTheDocument()
  })

  it('offers project creation when the portfolio is empty', async () => {
    stubApi({ '/projects': [] })
    renderPage(<PortfolioPage />)

    expect(await screen.findByText('No projects yet')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'New project' }).length)
      .toBeGreaterThan(0)
  })

  it('surfaces a server error with its code', async () => {
    stubApi({
      '/projects': new Response(
        JSON.stringify({ error: { code: 'forbidden', message: 'Not allowed' } }),
        { status: 403 }),
    })
    renderPage(<PortfolioPage />)

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Not allowed')).toBeInTheDocument()
    expect(screen.getByText('Code: forbidden')).toBeInTheDocument()
  })
})

describe('approval inbox', () => {
  const inbox = {
    candidates: [{ itemId: 'epic-1', stableId: 'EPIC-001', type: 'epic',
                   title: 'Customer accounts', currentVersion: 2,
                   approvedVersion: 1, requiresReapproval: true, stale: false }],
    pendingCount: 1, canDecide: true, canWaive: true,
  }

  it('lists candidates with their renewal flags', async () => {
    stubApi({ '/approvals/inbox': inbox, '/approvals/events': [] })
    renderPage(<ApprovalsPage />, { path: '/', route: '/' })

    expect(await screen.findByText('EPIC-001')).toBeInTheDocument()
    expect(screen.getByText('needs renewal')).toBeInTheDocument()
    expect(screen.getByText(/approved v1/)).toBeInTheDocument()
  })

  it('shows the manifest, blockers and the reference only entry', async () => {
    stubApi({ '/approvals/inbox': inbox, '/approvals/events': [],
              '/approvals/preview/': MANIFEST })
    renderPage(<ApprovalsPage />)

    await userEvent.click(await screen.findByRole('button', { name: 'Preview bundle' }))

    expect(await screen.findByRole('dialog',
                                   { name: /Approval bundle/ })).toBeInTheDocument()
    expect(screen.getByText('STORY-001 has no linked test case')).toBeInTheDocument()
    expect(screen.getByText('This blocker cannot be waived.')).toBeInTheDocument()
    expect(screen.getByText('Reference only')).toBeInTheDocument()
    expect(screen.getByText(/24 person hours/)).toBeInTheDocument()
    // The manifest hash is shown truncated so the approver can cite it.
    expect(screen.getByText(/hash-abc123def45/)).toBeInTheDocument()
    expect(screen.getByText(/fails atomically|nothing is approved/i))
      .toBeInTheDocument()
  })

  it('keeps approval disabled until every critical blocker is waived', async () => {
    stubApi({ '/approvals/inbox': inbox, '/approvals/events': [],
              '/approvals/preview/': MANIFEST })
    renderPage(<ApprovalsPage />)

    await userEvent.click(await screen.findByRole('button', { name: 'Preview bundle' }))
    const approve = await screen.findByRole('button', { name: 'Approve bundle' })
    expect(approve).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Waive with rationale' }))
    await userEvent.type(screen.getByPlaceholderText('Recorded rationale'),
                         'Covered by the regression suite')
    await userEvent.click(screen.getByRole('button', { name: 'Record waiver' }))

    expect(screen.getByText(/Rationale: Covered by the regression suite/))
      .toBeInTheDocument()
    // The non waivable blocker still holds the decision.
    expect(screen.getByRole('button', { name: 'Approve bundle' })).toBeDisabled()
  })

  it('explains a version conflict instead of silently failing', async () => {
    const manifest = { ...MANIFEST, blockers: [] }
    stubApi({
      '/approvals/inbox': inbox,
      '/approvals/events': [],
      '/approvals/preview/': manifest,
      '/approvals/decisions': new Response(
        JSON.stringify({ error: { code: 'version_conflict',
                                  message: 'An item changed while the approval was '
                                           + 'being submitted.',
                                  details: { refreshedManifestId: 'm2' } } }),
        { status: 409 }),
    })
    renderPage(<ApprovalsPage />)

    await userEvent.click(await screen.findByRole('button', { name: 'Preview bundle' }))
    const approve = await screen.findByRole('button', { name: 'Approve bundle' })
    expect(approve).toBeEnabled()
    await userEvent.click(approve)

    await waitFor(() =>
      expect(screen.getByText(/Nothing was approved/)).toBeInTheDocument())
    expect(screen.getByText('Code: version_conflict')).toBeInTheDocument()
  })
})

describe('client workspace', () => {
  const workspace = {
    projectId: 'p1',
    items: [{ id: 'story-1', stableId: 'STORY-001', type: 'story',
              title: 'Customer registers', description: 'Self service registration',
              version: 1, state: 'approved', isDraft: false,
              acceptanceCriteria: [{ id: 'AC-1', text: 'A customer can register' }],
              businessRules: [], assumptions: [], clientAccepted: false }],
    questions: [], tests: [], specifications: [],
    allowAcceptance: true, allowDownload: false, includesDrafts: false,
    note: 'You are viewing versions explicitly shared with you.',
  }

  it('shows only shared versions and the sharing note', async () => {
    stubApi({
      '/client/projects/p1/workspace': workspace,
      '/client/projects': [{ projectId: 'p1', name: 'Customer Portal', items: 1,
                             allowAcceptance: true, expiresAt: null }],
    })
    renderPage(<ClientPage />)

    expect(await screen.findByText('Customer registers')).toBeInTheDocument()
    expect(screen.getByText(/explicitly shared with you/)).toBeInTheDocument()
    expect(screen.getByText('A customer can register')).toBeInTheDocument()
    expect(screen.getByText('approved v1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument()
  })

  it('states plainly when nothing has been shared', async () => {
    stubApi({ '/client/projects': [] })
    renderPage(<ClientPage />)
    expect(await screen.findByText('Nothing has been shared with you yet'))
      .toBeInTheDocument()
  })

  it('warns when the shared selection includes drafts', async () => {
    stubApi({
      '/client/projects/p1/workspace': {
        ...workspace, includesDrafts: true,
        items: [{ ...workspace.items[0], isDraft: true, state: 'draft' }],
      },
      '/client/projects': [{ projectId: 'p1', name: 'Customer Portal', items: 1,
                             allowAcceptance: true, expiresAt: null }],
    })
    renderPage(<ClientPage />)

    expect(await screen.findByText(/includes draft versions/)).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()
  })
})

describe('loading and failure states', () => {
  const failure = () => new Response(JSON.stringify({
    error: { code: 'unavailable', message: 'Service unavailable' } }), { status: 503 })

  it('keeps the page heading and title while loading and after a failure', async () => {
    stubApi({ '/projects': failure })
    renderPage(<PortfolioPage />)
    expect(screen.getByRole('heading', { level: 1, name: 'Project portfolio' }))
      .toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('Service unavailable')
    expect(screen.getByRole('heading', { level: 1, name: 'Project portfolio' }))
      .toBeInTheDocument()
    expect(document.title).toContain('Project portfolio')
  })

  it('shows a project setup load failure instead of loading forever', async () => {
    stubApi({ '/projects/p1': failure })
    renderPage(<ProjectSetupPage />, {
      path: '/projects/:projectId/setup', route: '/projects/p1/setup' })
    expect(await screen.findByRole('alert')).toHaveTextContent('Service unavailable')
    expect(screen.getByRole('heading', { level: 1, name: 'Project setup' }))
      .toBeInTheDocument()
  })
})
