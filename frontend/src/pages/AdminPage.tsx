/** Screen 14 — administration: models, jobs, calibration and audit. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import {
  Badge, ErrorBanner, Note, PageHeader, Section, Spinner, Table, Tabs, formatDateTime,
} from '../components/ui'

interface CalibrationVersion {
  id: string
  status: string
  createdAt: string
  cohortSize: number
  usableSize: number
  sufficient: boolean
  ratios: Record<string, number>
  evaluation: Record<string, unknown>
}

export function AdminPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('models')

  const models = useQuery({
    queryKey: ['admin-models'],
    queryFn: () => api<{ adapters: Record<string, unknown>[]
                         configuration: Record<string, unknown>; note: string }>(
      '/admin/models'),
  })
  const jobs = useQuery({
    queryKey: ['admin-jobs'],
    queryFn: () => api<Record<string, unknown>[]>('/admin/jobs'),
    refetchInterval: 10_000,
  })
  const calibration = useQuery({
    queryKey: ['admin-calibration'],
    queryFn: () => api<CalibrationVersion[]>('/admin/calibration'),
  })
  const users = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => api<{ id: string; email: string; displayName: string
                         globalRoles: string[]; isClient: boolean; active: boolean }[]>(
      '/admin/users'),
  })

  const buildCandidate = useMutation({
    mutationFn: () => api('/admin/calibration/candidates', { method: 'POST', body: {} }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-calibration'] }),
  })
  const activate = useMutation({
    mutationFn: (id: string) =>
      api(`/admin/calibration/${id}/activate`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-calibration'] }),
  })
  const rollback = useMutation({
    mutationFn: (id: string) =>
      api(`/admin/calibration/${id}/rollback`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-calibration'] }),
  })

  return (
    <>
      <PageHeader title={t('adminTitle')} subtitle={t('adminSubtitle')} />

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: 'models', label: t('models') },
        { key: 'jobs', label: t('jobs'), count: jobs.data?.length },
        { key: 'calibration', label: t('calibration'), count: calibration.data?.length },
        { key: 'users', label: 'Accounts', count: users.data?.length },
      ]} />

      {tab === 'models' ? (
        models.isLoading ? <Spinner /> : (
          <div className="space-y-4">
            <Section title="Model adapters"
                     description="Local and cloud adapters with health and capability metadata.">
              <div className="space-y-2">
                {(models.data?.adapters ?? []).map((adapter, index) => (
                  <div key={index}
                       className="flex flex-wrap items-center gap-2 rounded border
                                  border-ink-200 px-3 py-2 text-sm">
                    <Badge tone={adapter.healthy ? 'good' : 'warning'}>
                      {String(adapter.deployment)}
                    </Badge>
                    <span className="font-medium">{String(adapter.modelId ?? '—')}</span>
                    <span className="text-ink-500">{String(adapter.detail ?? '')}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3">
                <Note tone="muted">{models.data?.note}</Note>
              </div>
            </Section>

            <Section title="Deployment configuration">
              <pre className="overflow-x-auto rounded-lg bg-ink-50 p-3 text-xs">
                {JSON.stringify(models.data?.configuration ?? {}, null, 2)}
              </pre>
            </Section>
          </div>
        )
      ) : null}

      {tab === 'jobs' ? (
        <Section title="Background jobs"
                 description="Long running work is queued, observable and restartable.">
          <Table
            rows={(jobs.data ?? []) as Record<string, string | number>[]}
            rowKey={(row) => String(row.id)}
            empty="No jobs recorded"
            columns={[
              { key: 'kind', header: 'Kind', render: (row) => String(row.kind) },
              { key: 'status', header: 'Status',
                render: (row) => <Badge tone={row.status === 'succeeded' ? 'good'
                  : row.status === 'failed' ? 'critical' : 'info'}>
                  {String(row.status)}</Badge> },
              { key: 'progress', header: 'Progress', align: 'right',
                render: (row) => `${Math.round(Number(row.progress) * 100)}%` },
              { key: 'attempts', header: 'Attempts', align: 'right',
                render: (row) => String(row.attempts) },
              { key: 'created', header: 'Created',
                render: (row) => formatDateTime(String(row.createdAt)) },
              { key: 'message', header: 'Message',
                render: (row) => String(row.error ?? row.message ?? '—') },
            ]} />
        </Section>
      ) : null}

      {tab === 'calibration' ? (
        <div className="space-y-4">
          <Section title="Historical calibration"
                   description="Candidates are evaluated on a time separated holdout and need administrator approval before activation."
                   actions={
                     <button type="button" className="btn-primary"
                             disabled={buildCandidate.isPending}
                             onClick={() => buildCandidate.mutate()}>
                       Build candidate
                     </button>
                   }>
            {buildCandidate.error ? <ErrorBanner error={buildCandidate.error} /> : null}
            {activate.error ? <ErrorBanner error={activate.error} /> : null}
            <div className="space-y-3">
              {(calibration.data ?? []).map((version) => (
                <article key={version.id} className="rounded-lg border border-ink-200 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={version.status === 'active' ? 'good'
                      : version.status === 'candidate' ? 'info' : 'muted'}>
                      {version.status}
                    </Badge>
                    <span className="text-xs text-ink-500">
                      {formatDateTime(version.createdAt)}
                    </span>
                    <Badge tone="muted">
                      cohort {version.usableSize}/{version.cohortSize}
                    </Badge>
                    {version.sufficient
                      ? null
                      : <Badge tone="warning">insufficient evidence</Badge>}
                  </div>
                  {version.sufficient ? (
                    <>
                      <p className="mt-1 text-sm text-ink-700">
                        Ratios: {Object.entries(version.ratios)
                          .map(([key, value]) => `${key} ×${value}`).join(', ')}
                      </p>
                      <pre className="mt-2 overflow-x-auto rounded bg-ink-50 p-2 text-xs">
                        {JSON.stringify(version.evaluation, null, 2)}
                      </pre>
                      <div className="mt-2 flex gap-2">
                        {version.status === 'candidate' ? (
                          <button type="button" className="btn-secondary text-xs"
                                  onClick={() => activate.mutate(version.id)}>
                            Activate
                          </button>
                        ) : null}
                        {version.status === 'active' ? (
                          <button type="button" className="btn-danger text-xs"
                                  onClick={() => rollback.mutate(version.id)}>
                            Roll back
                          </button>
                        ) : null}
                      </div>
                    </>
                  ) : (
                    <p className="mt-1 text-sm text-amber-800">
                      {String(version.evaluation.message ?? '')}
                    </p>
                  )}
                </article>
              ))}
              {!calibration.data?.length ? (
                <p className="py-6 text-center text-sm text-ink-500">
                  No calibration candidate yet. Template estimates remain in use and no
                  learned accuracy is claimed.
                </p>
              ) : null}
            </div>
          </Section>
        </div>
      ) : null}

      {tab === 'users' ? (
        <Section title="Accounts"
                 description="Infrastructure administration does not grant project content access.">
          <Table
            rows={users.data ?? []}
            rowKey={(row) => row.id}
            columns={[
              { key: 'name', header: 'Name', render: (row) => row.displayName },
              { key: 'email', header: 'Email', render: (row) => row.email },
              { key: 'roles', header: 'Platform roles',
                render: (row) => row.globalRoles.length
                  ? row.globalRoles.join(', ')
                  : <span className="text-ink-500">project scoped only</span> },
              { key: 'client', header: 'Client',
                render: (row) => row.isClient ? <Badge tone="warning">client</Badge> : '—' },
              { key: 'active', header: 'Active',
                render: (row) => row.active
                  ? <Badge tone="good">active</Badge>
                  : <Badge tone="muted">disabled</Badge> },
            ]} />
        </Section>
      ) : null}
    </>
  )
}
