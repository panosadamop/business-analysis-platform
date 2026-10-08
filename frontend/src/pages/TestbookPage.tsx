/** Screen 9 — testbook workspace: cases, Gherkin, coverage and versioned assembly. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import { StatTile } from '../components/charts'
import { AddTestCaseModal } from '../components/entry-forms'
import {
  Badge, ErrorBanner, Modal, Note, PageHeader, Section, Spinner, StateBadge, Table, Tabs,
} from '../components/ui'
import type { BacklogNode, CoverageMatrix, TestCase } from '../types'

export function TestbookPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('cases')
  const [selected, setSelected] = useState<TestCase | null>(null)
  const [writing, setWriting] = useState(false)

  const tests = useQuery({
    queryKey: ['tests', projectId],
    queryFn: () => api<TestCase[]>(`/projects/${projectId}/tests`),
  })
  const coverage = useQuery({
    queryKey: ['coverage', projectId],
    queryFn: () => api<CoverageMatrix>(`/projects/${projectId}/tests/coverage`),
  })
  const tree = useQuery({
    queryKey: ['backlog-tree', projectId],
    queryFn: () => api<BacklogNode[]>(`/projects/${projectId}/backlog/tree`),
  })
  const books = useQuery({
    queryKey: ['testbooks', projectId],
    queryFn: () => api<{ id: string; name: string; version: number; state: string
                         assembledAt?: string | null; gaps: unknown[]
                         coverage: Record<string, unknown> }[]>(
      `/projects/${projectId}/testbooks`),
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/tests`, { method: 'POST', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tests', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['coverage', projectId] })
      setWriting(false)
    },
  })
  const assemble = useMutation({
    mutationFn: () => api(`/projects/${projectId}/testbooks`, {
      method: 'POST', body: { name: 'Project testbook' },
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['testbooks', projectId] }),
  })

  return (
    <>
      <PageHeader title={t('testbookTitle')} subtitle={t('testbookSubtitle')}
                  actions={
                    <>
                      <button type="button" className="btn-secondary"
                              onClick={() => setWriting(true)}>Write a test case</button>
                      <button type="button" className="btn-primary"
                              disabled={assemble.isPending}
                              onClick={() => assemble.mutate()}>
                        {t('assembleTestbook')}
                      </button>
                    </>
                  } />

      {coverage.data ? (
        <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile label="Criteria covered" value={`${coverage.data.coveredPercent}%`}
                    tone={coverage.data.coveredPercent > 90 ? 'good'
                      : coverage.data.coveredPercent > 60 ? 'warning' : 'critical'}
                    hint={`${coverage.data.totalCriteria} criteria in scope`} />
          <StatTile label={t('uncovered')} value={coverage.data.uncoveredCriteria}
                    tone={coverage.data.uncoveredCriteria ? 'warning' : 'good'} />
          <StatTile label="Test cases" value={coverage.data.totalTests} />
          <StatTile label="Tests with no requirement"
                    value={coverage.data.unlinkedTests.length}
                    tone={coverage.data.unlinkedTests.length ? 'warning' : 'good'} />
        </div>
      ) : null}

      <div className="mb-4">
        <Note tone="muted">
          Generation never records a run status. Every generated case is a draft awaiting review.
        </Note>
      </div>

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: 'cases', label: 'Test cases', count: tests.data?.length },
        { key: 'coverage', label: t('coverage'), count: coverage.data?.uncoveredCriteria },
        { key: 'books', label: 'Assembled books', count: books.data?.length },
      ]} />

      {tab === 'cases' ? (
        tests.isLoading ? <Spinner /> : (
          <Section title="Test cases">
            <Table
              rows={tests.data ?? []}
              rowKey={(row) => row.id}
              onRowClick={setSelected}
              empty="No test cases yet. The QA analyst stage generates descriptive cases and Gherkin."
              columns={[
                { key: 'id', header: 'ID', render: (row) => row.stableId },
                { key: 'title', header: 'Title', render: (row) => row.title },
                { key: 'type', header: 'Type',
                  render: (row) => <Badge tone={
                    row.testType === 'permissions' ? 'warning'
                      : row.testType === 'negative' ? 'info' : 'muted'}>{row.testType}</Badge> },
                { key: 'criteria', header: 'Criteria',
                  render: (row) => row.criterionIds.length
                    ? row.criterionIds.join(', ')
                    : <span className="text-amber-700">unlinked</span> },
                { key: 'state', header: 'State',
                  render: (row) => <StateBadge state={row.state} /> },
                { key: 'review', header: 'Review', render: (row) => row.reviewState },
              ]} />
          </Section>
        )
      ) : null}

      {tab === 'coverage' ? (
        <Section title={t('coverage')}
                 description="Criteria with no test and tests with no linked requirement are both flagged.">
          <Table
            rows={coverage.data?.rows ?? []}
            rowKey={(row) => row.criterionId}
            columns={[
              { key: 'item', header: 'Item',
                render: (row) => `${row.itemStableId} — ${row.itemTitle}` },
              { key: 'criterion', header: 'Criterion', render: (row) => row.criterionText },
              { key: 'tests', header: 'Tests',
                render: (row) => row.testIds.length
                  ? row.testIds.join(', ')
                  : <Badge tone="warning">no test</Badge> },
            ]} />
          {coverage.data?.unlinkedTests.length ? (
            <div className="mt-4">
              <h3 className="mb-1 text-sm font-semibold text-ink-900">
                Tests with no linked requirement
              </h3>
              <ul className="space-y-1 text-sm">
                {coverage.data.unlinkedTests.map((test) => (
                  <li key={test.stableId} className="text-amber-800">
                    {test.stableId} — {test.title}: {test.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Section>
      ) : null}

      {tab === 'books' ? (
        <Section title="Assembled testbooks"
                 description="Versioned plan with manifest, suites, coverage and unresolved gaps.">
          <Table
            rows={books.data ?? []}
            rowKey={(row) => row.id}
            empty="No testbook assembled yet"
            columns={[
              { key: 'name', header: 'Name', render: (row) => row.name },
              { key: 'version', header: 'Version', align: 'right',
                render: (row) => `v${row.version}` },
              { key: 'state', header: 'State',
                render: (row) => <StateBadge state={row.state} /> },
              { key: 'coverage', header: 'Covered', align: 'right',
                render: (row) => `${String(row.coverage?.coveredPercent ?? 0)}%` },
              { key: 'gaps', header: 'Gaps', align: 'right',
                render: (row) => row.gaps.length },
            ]} />
        </Section>
      ) : null}

      {selected ? (
        <TestDetail projectId={projectId} test={selected} onClose={() => setSelected(null)} />
      ) : null}

      <AddTestCaseModal open={writing} onClose={() => setWriting(false)}
                        onCreate={(body) => create.mutate(body)}
                        busy={create.isPending} error={create.error}
                        stories={flattenStories(tree.data ?? [])} />
    </>
  )
}

function TestDetail({ projectId, test, onClose }: {
  projectId: string; test: TestCase; onClose: () => void
}) {
  const { t } = useI18n()
  const [dialect, setDialect] = useState<'en' | 'el'>('en')

  const gherkin = useQuery({
    queryKey: ['gherkin', projectId, test.id, dialect],
    queryFn: () => api<{ text: string | null; validation?: { valid: boolean
                         errors: { message: string }[] } }>(
      `/projects/${projectId}/tests/${test.id}/gherkin`, { query: { dialect } }),
  })

  return (
    <Modal open wide title={`${test.stableId} — ${test.title}`} onClose={onClose}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="muted">{test.testType}</Badge>
          <Badge tone="muted">{test.priority}</Badge>
          <StateBadge state={test.state} />
          <Badge tone={test.reviewState === 'approved' ? 'good' : 'warning'}>
            {test.reviewState}
          </Badge>
        </div>

        {test.objective ? (
          <p className="text-sm text-ink-700"><strong>Objective. </strong>{test.objective}</p>
        ) : null}

        {test.preconditions.length ? (
          <section>
            <h3 className="text-sm font-semibold text-ink-900">Preconditions</h3>
            <ul className="list-disc pl-5 text-sm text-ink-700">
              {test.preconditions.map((item, index) => <li key={index}>{item}</li>)}
            </ul>
          </section>
        ) : null}

        {test.steps.length ? (
          <section>
            <h3 className="text-sm font-semibold text-ink-900">Steps</h3>
            <ol className="space-y-1 text-sm">
              {test.steps.map((step) => (
                <li key={step.ordinal} className="rounded border border-ink-200 px-2 py-1">
                  <strong>{step.ordinal}.</strong> {step.action}
                  {step.expected ? (
                    <span className="block text-xs text-ink-500">Expected: {step.expected}</span>
                  ) : null}
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        <section>
          <div className="mb-1 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink-900">{t('gherkin')}</h3>
            <div className="flex gap-1">
              {(['en', 'el'] as const).map((code) => (
                <button key={code} type="button"
                        className={`rounded px-2 py-0.5 text-xs ${
                          dialect === code ? 'bg-brand-600 text-white' : 'text-ink-600'}`}
                        onClick={() => setDialect(code)}>
                  {code.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          {gherkin.isLoading ? <Spinner /> : null}
          {gherkin.error ? <ErrorBanner error={gherkin.error} /> : null}
          {gherkin.data?.text ? (
            <>
              <pre className="overflow-x-auto rounded-lg bg-code p-3 text-xs
                              text-code-text">{gherkin.data.text}</pre>
              {gherkin.data.validation ? (
                <p className={`mt-1 text-xs ${
                  gherkin.data.validation.valid ? 'text-emerald-700' : 'text-red-700'}`}>
                  {gherkin.data.validation.valid
                    ? 'Structurally valid. Semantic quality still requires review.'
                    : gherkin.data.validation.errors.map((error) => error.message).join('; ')}
                </p>
              ) : null}
            </>
          ) : (
            <Note tone="muted">This test has no Gherkin scenario yet.</Note>
          )}
          <p className="mt-1 text-xs text-ink-500">
            One canonical scenario structure is stored; the dialect above is a display
            rendering, so a translation never creates a duplicate test.
          </p>
        </section>
      </div>
    </Modal>
  )
}

/** Stories are the only level a test case links to for coverage. */
function flattenStories(nodes: BacklogNode[]): BacklogNode[] {
  return nodes.flatMap((node) => [
    ...(node.type === 'story' ? [node] : []),
    ...flattenStories(node.children),
  ])
}
