/** Screen 1 — project portfolio: health, pending decisions and budget visibility. */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import { DEFAULT_ANALYSTS, AnalystPicker } from '../components/analysts'
import { StatTile } from '../components/charts'
import {
  Badge, EmptyState, ErrorBanner, Field, Modal, PageHeader, Spinner, money,
} from '../components/ui'
import type { ProjectHealth } from '../types'

export function PortfolioPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)

  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api<ProjectHealth[]>('/projects'),
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api('/projects', { method: 'POST', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
      setCreating(false)
    },
  })

  // The screen keeps its heading (and so its document title) while it loads or fails.
  const loadingHeader = <PageHeader title={t('portfolioTitle')} subtitle={t('portfolioSubtitle')} />
  if (projects.isLoading) return <>{loadingHeader}<Spinner /></>
  if (projects.error) return <>{loadingHeader}<ErrorBanner error={projects.error} onRetry={projects.refetch} /></>

  const rows = projects.data ?? []
  const totals = rows.reduce(
    (acc, row) => ({
      pending: acc.pending + row.pendingApprovals,
      critical: acc.critical + row.openCriticalQuestions,
      findings: acc.findings + row.unresolvedFindings,
      estimated: acc.estimated + row.estimatedHours,
      actual: acc.actual + row.actualHours,
    }),
    { pending: 0, critical: 0, findings: 0, estimated: 0, actual: 0 },
  )

  return (
    <>
      <PageHeader
        title={t('portfolioTitle')}
        subtitle={t('portfolioSubtitle')}
        actions={
          <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
            {t('newProject')}
          </button>
        }
      />

      {rows.length ? (
        <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile label={t('pendingApprovals')} value={totals.pending}
                    tone={totals.pending ? 'warning' : 'good'}
                    hint="Items with no approval or needing renewal" />
          <StatTile label={t('criticalQuestions')} value={totals.critical}
                    tone={totals.critical ? 'critical' : 'good'}
                    hint="Unresolved and blocking approval" />
          <StatTile label={t('openFindings')} value={totals.findings}
                    tone={totals.findings ? 'warning' : 'neutral'} />
          <StatTile label={t('estimatedHours')} value={Math.round(totals.estimated)}
                    unit="h" hint={`${Math.round(totals.actual)} h recorded`} />
        </div>
      ) : null}

      {rows.length === 0 ? (
        <EmptyState
          title="No projects yet"
          hint="Create a project, upload its evidence and run the analyst workflow."
          action={<button type="button" className="btn-primary"
                          onClick={() => setCreating(true)}>{t('newProject')}</button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {rows.map((project) => (
            <article key={project.projectId} className="card card-pad">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <Link to={`/projects/${project.projectId}/evidence`}
                        className="text-sm font-semibold text-brand-700 hover:underline">
                    {project.key} — {project.name}
                  </Link>
                  <p className="text-xs text-ink-500">
                    {project.clientName ?? 'Internal'} · {project.deliveryMethod}
                  </p>
                </div>
                {project.localOnly
                  ? <Badge tone="good" icon="🔒">{t('localOnly')}</Badge>
                  : <Badge tone="warning" icon="☁">{t('cloudAllowed')}</Badge>}
              </div>

              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <Metric label={t('stories')}
                        value={`${project.approvedStories}/${project.stories}`}
                        hint={t('approved')} />
                <Metric label={t('pendingApprovals')} value={project.pendingApprovals}
                        tone={project.pendingApprovals ? 'warning' : 'good'} />
                <Metric label={t('criticalQuestions')} value={project.openCriticalQuestions}
                        tone={project.openCriticalQuestions ? 'critical' : 'good'} />
                <Metric label={t('openFindings')} value={project.unresolvedFindings} />
                <Metric label={t('estimatedHours')} value={Math.round(project.estimatedHours)} />
                <Metric label={t('actualHours')} value={Math.round(project.actualHours)} />
              </dl>

              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-100 pt-3">
                <Badge tone="muted">
                  {t('connector')}: {project.connectorHealth.replace('_', ' ')}
                </Badge>
                {project.forecastCost ? (
                  <Badge tone="muted">Forecast {money(project.forecastCost)}</Badge>
                ) : null}
                {project.nextMilestone ? (
                  <Badge tone="info">Next: {project.nextMilestone}</Badge>
                ) : null}
              </div>

              <nav className="mt-3 flex flex-wrap gap-2 text-xs">
                {[
                  ['evidence', t('navEvidence')],
                  ['analysis', t('navAnalysis')],
                  ['backlog', t('navBacklog')],
                  ['approvals', t('navApprovals')],
                  ['dashboards', t('navDashboards')],
                ].map(([path, label]) => (
                  <Link key={path} to={`/projects/${project.projectId}/${path}`}
                        className="rounded border border-ink-200 px-2 py-1 text-ink-600
                                   hover:bg-ink-50">
                    {label}
                  </Link>
                ))}
              </nav>
            </article>
          ))}
        </div>
      )}

      <NewProjectModal open={creating} onClose={() => setCreating(false)}
                       onCreate={(body) => create.mutate(body)}
                       error={create.error} busy={create.isPending} />
    </>
  )
}

function Metric({ label, value, hint, tone }: {
  label: string; value: string | number; hint?: string; tone?: string
}) {
  const toneClass = tone === 'critical' ? 'text-red-700'
    : tone === 'warning' ? 'text-amber-700'
    : tone === 'good' ? 'text-emerald-700' : 'text-ink-900'
  return (
    <div>
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className={`font-medium tabular-nums ${toneClass}`}>
        {value}{hint ? <span className="ml-1 text-xs font-normal text-ink-500">{hint}</span> : null}
      </dd>
    </div>
  )
}

function NewProjectModal({ open, onClose, onCreate, error, busy }: {
  open: boolean
  onClose: () => void
  onCreate: (body: Record<string, unknown>) => void
  error: unknown
  busy: boolean
}) {
  const [form, setForm] = useState({
    key: '', name: '', clientName: '', outputLanguage: 'en',
    deliveryMethod: 'scrum', defaultClassification: 'confidential', currency: 'EUR',
    languages: ['en', 'el'] as string[],
    enabledAnalysts: DEFAULT_ANALYSTS,
  })

  return (
    <Modal open={open} title="New project" onClose={onClose}
           footer={
             <>
               <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
               <button type="button" className="btn-primary" disabled={busy || !form.key}
                       onClick={() => onCreate(form)}>Create project</button>
             </>
           }>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Key" hint="Short unique code, for example PORTAL">
          <input className="input" value={form.key}
                 onChange={(event) => setForm({ ...form, key: event.target.value.toUpperCase() })} />
        </Field>
        <Field label="Name">
          <input className="input" value={form.name}
                 onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
        <Field label="Client">
          <input className="input" value={form.clientName}
                 onChange={(event) => setForm({ ...form, clientName: event.target.value })} />
        </Field>
        <Field label="Delivery method">
          <select className="input" value={form.deliveryMethod}
                  onChange={(event) => setForm({ ...form, deliveryMethod: event.target.value })}>
            <option value="scrum">Scrum</option>
            <option value="kanban">Kanban</option>
          </select>
        </Field>
        <Field label="Output language" hint="Independent of the evidence language">
          <select className="input" value={form.outputLanguage}
                  onChange={(event) => setForm({ ...form, outputLanguage: event.target.value })}>
            <option value="en">English</option>
            <option value="el">Ελληνικά</option>
          </select>
        </Field>
        <Field label="Default classification"
               hint="Restricted content never leaves company infrastructure">
          <select className="input" value={form.defaultClassification}
                  onChange={(event) =>
                    setForm({ ...form, defaultClassification: event.target.value })}>
            <option value="restricted">Restricted</option>
            <option value="confidential">Confidential</option>
            <option value="shareable">Shareable</option>
          </select>
        </Field>
        <div className="sm:col-span-2">
          <AnalystPicker value={form.enabledAnalysts}
                         onChange={(enabledAnalysts) => setForm({ ...form, enabledAnalysts })} />
        </div>
      </div>
      {error ? <div className="mt-3"><ErrorBanner error={error} /></div> : null}
      <p className="mt-3 text-xs text-ink-500">
        Cloud AI is disabled by default for every new project. Enable it per project only
        after the permitted disclosure has been agreed.
      </p>
    </Modal>
  )
}
