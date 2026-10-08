/** Screen 4 — analysis workspace: role stages, findings, questions and reruns. */
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import { DEFAULT_ANALYSTS, analystLabel } from '../components/analysts'
import {
  AddQuestionModal, AddRequirementModal, AddTermModal,
} from '../components/entry-forms'
import {
  Badge, EmptyState, ErrorBanner, Modal, Note, PageHeader, ProvenanceBadge, Section,
  SeverityBadge, Spinner, Table, Tabs, formatDateTime,
} from '../components/ui'
import type {
  AnalysisJob, GlossaryTerm, Project, Question, Requirement, ReviewFinding,
} from '../types'

export function AnalysisPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('runs')
  const [waiving, setWaiving] = useState<ReviewFinding | null>(null)
  const [adding, setAdding] = useState<'requirement' | 'question' | 'term' | null>(null)

  const runs = useQuery({
    queryKey: ['analysis-runs', projectId],
    queryFn: () => api<AnalysisJob[]>(`/projects/${projectId}/analysis/runs`),
    refetchInterval: (query) => {
      const data = query.state.data as AnalysisJob[] | undefined
      return data?.some((job) => ['queued', 'running'].includes(job.status)) ? 3000 : false
    },
  })
  const findings = useQuery({
    queryKey: ['findings', projectId],
    queryFn: () => api<ReviewFinding[]>(`/projects/${projectId}/findings`),
  })
  const questions = useQuery({
    queryKey: ['questions', projectId],
    queryFn: () => api<Question[]>(`/projects/${projectId}/questions`),
  })
  const requirements = useQuery({
    queryKey: ['requirements', projectId],
    queryFn: () => api<Requirement[]>(`/projects/${projectId}/requirements`),
  })
  const glossary = useQuery({
    queryKey: ['glossary', projectId],
    queryFn: () => api<GlossaryTerm[]>(`/projects/${projectId}/glossary`),
  })

  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api<Project>(`/projects/${projectId}`),
  })
  const analysts = project.data?.enabledAnalysts ?? DEFAULT_ANALYSTS
  const analystSequence = analysts.map(analystLabel).join(' → ')

  // No roles in the request: the server runs the project's chosen analysts.
  const start = useMutation({
    mutationFn: () => api(`/projects/${projectId}/analysis/runs`, {
      method: 'POST',
      body: { generateSpecifications: true, generateTests: true },
      idempotencyKey: `run-${Date.now()}`,
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['analysis-runs', projectId] }),
  })
  const cancel = useMutation({
    mutationFn: (jobId: string) =>
      api(`/projects/${projectId}/analysis/runs/${jobId}/cancel`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['analysis-runs', projectId] }),
  })
  const resume = useMutation({
    mutationFn: (jobId: string) =>
      api(`/projects/${projectId}/analysis/runs/${jobId}/resume`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['analysis-runs', projectId] }),
  })
  const resolveFinding = useMutation({
    mutationFn: ({ id, status, rationale }: { id: string; status: string; rationale?: string }) =>
      api(`/projects/${projectId}/findings/${id}/resolve`, {
        method: 'POST', body: { status, rationale },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['findings', projectId] })
      setWaiving(null)
    },
  })
  const resolveQuestion = useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) =>
      api(`/projects/${projectId}/questions/${id}/resolve`, {
        method: 'POST', body: { status: 'answered', answer },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['questions', projectId] }),
  })

  const createEntry = useMutation({
    mutationFn: ({ path, body }: { path: string; body: Record<string, unknown> }) =>
      api(`/projects/${projectId}/${path}`, { method: 'POST', body }),
    onSuccess: (_, variables) => {
      const key = variables.path === 'requirements' ? 'requirements'
        : variables.path === 'questions' ? 'questions' : 'glossary'
      void queryClient.invalidateQueries({ queryKey: [key, projectId] })
      setAdding(null)
    },
  })
  const deleteTerm = useMutation({
    mutationFn: (id: string) =>
      api(`/projects/${projectId}/glossary/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['glossary', projectId] }),
  })

  const openFindings = (findings.data ?? []).filter((f) => f.status === 'open')
  const openQuestions = (questions.data ?? []).filter((q) => q.status === 'open')

  return (
    <>
      <PageHeader
        title={t('analysisTitle')}
        subtitle={t('analysisSubtitle')}
        actions={
          <>
            <button type="button" className="btn-secondary"
                    onClick={() => setAdding('requirement')}>Add requirement</button>
            <button type="button" className="btn-secondary"
                    onClick={() => setAdding('question')}>Add question</button>
            <button type="button" className="btn-secondary"
                    onClick={() => setAdding('term')}>Add glossary term</button>
            <button type="button" className="btn-primary" disabled={start.isPending}
                    onClick={() => start.mutate()}>
              {start.isPending ? t('loading') : t('runAnalysis')}
            </button>
          </>
        }
      />

      <div className="mb-4 space-y-2">
        <Note>{t('generatedDraft')}</Note>
        <p className="text-sm text-ink-600">
          A run uses <span className="font-medium text-ink-800">{analystSequence}</span>.{' '}
          <Link to={`/projects/${projectId}/setup`} className="text-brand-700 underline">
            Change the analysts in the project setup
          </Link>
        </p>
      </div>
      {start.error ? <div className="mb-3"><ErrorBanner error={start.error} /></div> : null}

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: 'runs', label: 'Runs', count: runs.data?.length },
        { key: 'findings', label: t('findings'), count: openFindings.length },
        { key: 'questions', label: t('questions'), count: openQuestions.length },
        { key: 'requirements', label: t('requirements'), count: requirements.data?.length },
        { key: 'glossary', label: 'Glossary', count: glossary.data?.length },
      ]} />

      {tab === 'runs' ? (
        runs.isLoading ? <Spinner /> :
        !runs.data?.length ? (
          <EmptyState title="No analysis has run yet"
                      hint={`${analystSequence} run in sequence on the current evidence versions.`} />
        ) : (
          <div className="space-y-4">
            {runs.data.map((job) => (
              <Section key={job.id}
                       title={`Run ${formatDateTime(job.createdAt)}`}
                       description={job.message ?? undefined}
                       actions={
                         <div className="flex items-center gap-2">
                           <Badge tone={
                             job.status === 'succeeded' ? 'good'
                               : job.status === 'failed' ? 'critical'
                               : job.status === 'paused' ? 'warning' : 'info'}>
                             {job.status}
                           </Badge>
                           {['queued', 'running'].includes(job.status) ? (
                             <button type="button" className="btn-secondary text-xs"
                                     onClick={() => cancel.mutate(job.id)}>Cancel</button>
                           ) : null}
                           {['paused', 'failed'].includes(job.status) ? (
                             <button type="button" className="btn-secondary text-xs"
                                     onClick={() => resume.mutate(job.id)}>Resume</button>
                           ) : null}
                         </div>
                       }>
                <ol className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  {job.stages.map((stage) => (
                    <li key={stage.role} className="rounded-lg border border-ink-200 p-3">
                      <p className="flex items-center justify-between text-sm font-medium">
                        {analystLabel(stage.role)}
                        <Badge tone={
                          stage.status === 'succeeded' ? 'good'
                            : stage.status === 'failed' ? 'critical'
                            : stage.status === 'blocked' ? 'warning' : 'muted'}>
                          {stage.status}
                        </Badge>
                      </p>
                      {stage.usage ? (
                        <p className="mt-1 text-xs text-ink-500">
                          {stage.usage.deployment} · {stage.usage.modelId}
                          <br />prompt v{stage.usage.promptTemplateVersion} ·
                          {' '}{stage.usage.latencyMs} ms
                        </p>
                      ) : null}
                      {Object.keys(stage.outputSummary ?? {}).length ? (
                        <ul className="mt-2 space-y-0.5 text-xs text-ink-600">
                          {Object.entries(stage.outputSummary)
                            .filter(([, value]) => value)
                            .map(([key, value]) => (
                              <li key={key}>{key}: <strong>{value}</strong></li>
                            ))}
                        </ul>
                      ) : null}
                      {stage.error ? (
                        <p className="mt-2 text-xs text-red-700">{stage.error}</p>
                      ) : null}
                    </li>
                  ))}
                </ol>
                {job.warnings.length ? (
                  <ul className="mt-3 space-y-1">
                    {job.warnings.map((warning, index) => (
                      <li key={index} className="text-xs text-amber-700">
                        {warning.stage}: {warning.message}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </Section>
            ))}
          </div>
        )
      ) : null}

      {tab === 'findings' ? (
        <Section title={t('findings')}
                 description="A specialist review is never a human approval.">
          <Table
            rows={findings.data ?? []}
            rowKey={(row) => row.id}
            empty="No findings recorded"
            columns={[
              { key: 'severity', header: 'Severity',
                render: (row) => <SeverityBadge severity={row.severity} /> },
              { key: 'role', header: 'Role',
                render: (row) => analystLabel(row.role) },
              { key: 'title', header: 'Finding',
                render: (row) => (
                  <div>
                    <p className="font-medium text-ink-900">{row.title}</p>
                    <p className="text-xs text-ink-600">{row.rationale}</p>
                    {row.recommendation ? (
                      <p className="mt-0.5 text-xs text-brand-700">{row.recommendation}</p>
                    ) : null}
                  </div>
                ) },
              { key: 'status', header: 'Status',
                render: (row) => (
                  <Badge tone={row.status === 'open' ? 'warning'
                    : row.status === 'escalated' ? 'critical' : 'good'}>
                    {row.status}{row.blocking ? ' · blocking' : ''}
                  </Badge>
                ) },
              { key: 'actions', header: '', align: 'right',
                render: (row) => row.status === 'open' ? (
                  <div className="flex justify-end gap-1">
                    <button type="button" className="btn-secondary text-xs"
                            onClick={() => resolveFinding.mutate({
                              id: row.id, status: 'resolved' })}>
                      {t('resolve')}
                    </button>
                    <button type="button" className="btn-secondary text-xs"
                            onClick={() => setWaiving(row)}>{t('waive')}</button>
                  </div>
                ) : null },
            ]} />
        </Section>
      ) : null}

      {tab === 'questions' ? (
        <Section title={t('questions')}
                 description="Ambiguity, contradiction, duplication, missing rules and incomplete flows.">
          <div className="space-y-3">
            {(questions.data ?? []).map((question) => (
              <article key={question.id} className="rounded-lg border border-ink-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={question.severity} />
                  <Badge tone="muted">{question.kind.replace('_', ' ')}</Badge>
                  <Badge tone={question.status === 'open' ? 'warning' : 'good'}>
                    {question.status}
                  </Badge>
                  <span className="text-xs text-ink-500">{question.stableId}</span>
                </div>
                <p className="mt-1 text-sm font-medium text-ink-900">{question.title}</p>
                <p className="text-sm text-ink-600">{question.detail}</p>
                {question.proposedClarification ? (
                  <p className="mt-1 text-xs text-brand-700">
                    Proposed clarification: {question.proposedClarification}
                  </p>
                ) : null}
                {question.status === 'open' ? (
                  <form className="mt-2 flex gap-2"
                        onSubmit={(event) => {
                          event.preventDefault()
                          const value = new FormData(event.currentTarget).get('answer')
                          if (value) resolveQuestion.mutate({
                            id: question.id, answer: String(value) })
                        }}>
                    <input name="answer" className="input flex-1"
                           aria-label={`Answer to ${question.stableId}`}
                           placeholder="Record the decision and its owner" />
                    <button type="submit" className="btn-secondary">Record answer</button>
                  </form>
                ) : (
                  <p className="mt-1 text-sm text-emerald-800">{question.answer}</p>
                )}
              </article>
            ))}
            {!questions.data?.length ? (
              <p className="py-6 text-center text-sm text-ink-500">No open questions</p>
            ) : null}
          </div>
        </Section>
      ) : null}

      {tab === 'requirements' ? (
        <Section title={t('requirements')}
                 description="Evidence backed requirements, analyst assumptions and AI proposals are distinguished.">
          <Table
            rows={requirements.data ?? []}
            rowKey={(row) => row.id}
            empty="No requirements captured yet"
            columns={[
              { key: 'id', header: 'ID', render: (row) => row.stableId },
              { key: 'statement', header: 'Statement',
                render: (row) => (
                  <div>
                    <p className="font-medium text-ink-900">{row.title}</p>
                    <p className="text-xs text-ink-600">{row.statement}</p>
                    {row.citations.length ? (
                      <p className="mt-0.5 text-xs text-ink-500">
                        {row.citations.length} citation(s):
                        {' '}{row.citations.map((citation) =>
                          `${citation.locator.kind}:${citation.locator.value}`).join(', ')}
                      </p>
                    ) : (
                      <p className="mt-0.5 text-xs text-amber-700">No evidence locator</p>
                    )}
                  </div>
                ) },
              { key: 'type', header: 'Type', render: (row) => row.type.replace('_', ' ') },
              { key: 'provenance', header: t('provenance'),
                render: (row) => <ProvenanceBadge provenance={row.provenance} /> },
              { key: 'confidence', header: 'Confidence', align: 'right',
                render: (row) => (
                  <span title="A decision aid, not a calibrated probability">
                    {Math.round(row.confidence * 100)}%
                  </span>
                ) },
            ]} />
        </Section>
      ) : null}

      {tab === 'glossary' ? (
        <Section title="Project glossary"
                 description="Agreed terms, with their Greek and English wording."
                 actions={<button type="button" className="btn-secondary text-xs"
                                  onClick={() => setAdding('term')}>Add term</button>}>
          <Table
            rows={glossary.data ?? []}
            rowKey={(row) => row.id}
            empty="No glossary terms yet. Add the terms the client and the team must agree on."
            columns={[
              { key: 'term', header: 'Term', render: (row) => row.term },
              { key: 'definition', header: 'Definition', render: (row) => row.definition },
              { key: 'language', header: 'Language', render: (row) => row.language },
              { key: 'translations', header: 'Translations',
                render: (row) => Object.entries(row.translations).length
                  ? Object.entries(row.translations)
                      .map(([code, value]) => `${code}: ${value}`).join(' · ')
                  : '—' },
              { key: 'actions', header: '', align: 'right',
                render: (row) => (
                  <button type="button" className="btn-danger text-xs"
                          onClick={() => deleteTerm.mutate(row.id)}>Remove</button>
                ) },
            ]} />
        </Section>
      ) : null}

      <AddRequirementModal open={adding === 'requirement'}
                           onClose={() => setAdding(null)}
                           onCreate={(body) => createEntry.mutate(
                             { path: 'requirements', body })}
                           busy={createEntry.isPending} error={createEntry.error} />
      <AddQuestionModal open={adding === 'question'} onClose={() => setAdding(null)}
                        onCreate={(body) => createEntry.mutate(
                          { path: 'questions', body })}
                        busy={createEntry.isPending} error={createEntry.error} />
      <AddTermModal open={adding === 'term'} onClose={() => setAdding(null)}
                    onCreate={(body) => createEntry.mutate({ path: 'glossary', body })}
                    busy={createEntry.isPending} error={createEntry.error} />

      <Modal open={Boolean(waiving)} title="Waive finding"
             onClose={() => setWaiving(null)}
             footer={
               <>
                 <button type="button" className="btn-secondary"
                         onClick={() => setWaiving(null)}>Cancel</button>
                 <button type="button" className="btn-primary"
                         onClick={() => {
                           const input = document.getElementById('waiver') as HTMLTextAreaElement
                           if (waiving && input.value.trim()) {
                             resolveFinding.mutate({ id: waiving.id, status: 'waived',
                                                     rationale: input.value })
                           }
                         }}>Record waiver</button>
               </>
             }>
        <p className="mb-2 text-sm text-ink-700">{waiving?.title}</p>
        <textarea id="waiver" className="input h-24"
                  placeholder="Rationale (visible in the approval bundle and the audit record)" />
        <div className="mt-2">
          <Note tone="warning">
            A waiver is recorded against the approver and appears in the approval bundle.
          </Note>
        </div>
      </Modal>
    </>
  )
}
