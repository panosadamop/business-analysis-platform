/** Screen 12 — integration console: discovery, mappings, previews, conflicts. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import {
  Badge, EmptyState, ErrorBanner, Field, Modal, Note, PageHeader, Section, Spinner,
  Table, Tabs, formatDateTime,
} from '../components/ui'
import type { ApprovalEvent, Integration, PublicationPreview } from '../types'

const PROVIDERS = [
  { value: 'jira', label: 'Jira Cloud' },
  { value: 'azure_devops', label: 'Azure DevOps Boards' },
  { value: 'asana', label: 'Asana' },
]

export function IntegrationsPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('connectors')
  const [creating, setCreating] = useState(false)
  const [previewFor, setPreviewFor] = useState<Integration | null>(null)

  const integrations = useQuery({
    queryKey: ['integrations', projectId],
    queryFn: () => api<Integration[]>(`/projects/${projectId}/integrations`),
  })
  const health = useQuery({
    queryKey: ['integration-health', projectId],
    queryFn: () => api<Record<string, unknown>[]>(`/projects/${projectId}/integrations-health`),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['integrations', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['integration-health', projectId] })
  }

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/integrations`, { method: 'POST', body }),
    onSuccess: () => { invalidate(); setCreating(false) },
  })
  const discover = useMutation({
    mutationFn: (id: string) =>
      api(`/projects/${projectId}/integrations/${id}/discover`, { method: 'POST' }),
    onSuccess: invalidate,
  })
  const approveMapping = useMutation({
    mutationFn: (id: string) =>
      api(`/projects/${projectId}/integrations/${id}/approve-mapping`, { method: 'POST' }),
    onSuccess: invalidate,
  })
  const toggle = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api(`/projects/${projectId}/integrations/${id}`, { method: 'PATCH', body }),
    onSuccess: invalidate,
  })

  // The screen keeps its heading (and so its document title) while it loads or fails.
  const loadingHeader = <PageHeader title={t('integrationsTitle')} subtitle={t('integrationsSubtitle')} />
  if (integrations.isLoading) return <>{loadingHeader}<Spinner /></>
  if (integrations.error) return <>{loadingHeader}<ErrorBanner error={integrations.error} /></>

  const rows = integrations.data ?? []

  return (
    <>
      <PageHeader title={t('integrationsTitle')} subtitle={t('integrationsSubtitle')}
                  actions={<button type="button" className="btn-primary"
                                   onClick={() => setCreating(true)}>Add connector</button>} />

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: 'connectors', label: 'Connectors', count: rows.length },
        { key: 'health', label: 'Health' },
      ]} />

      {tab === 'connectors' ? (
        rows.length === 0 ? (
          <EmptyState title="No connector configured"
                      hint="Add Jira, Azure DevOps or Asana. Discovery runs first and a compatibility report precedes any mapping." />
        ) : (
          <div className="space-y-4">
            {rows.map((integration) => (
              <Section key={integration.id}
                       title={`${integration.name} — ${integration.provider.replace('_', ' ')}`}
                       description={integration.externalProjectKey
                         ? `External project ${integration.externalProjectKey}`
                         : undefined}
                       actions={
                         <div className="flex flex-wrap items-center gap-2">
                           <Badge tone={integration.health === 'healthy' ? 'good'
                             : integration.health === 'not_configured' ? 'muted' : 'warning'}>
                             {integration.health.replace('_', ' ')}
                           </Badge>
                           {integration.isPrimary ? <Badge tone="info">primary</Badge> : null}
                           <button type="button" className="btn-secondary text-xs"
                                   disabled={discover.isPending}
                                   onClick={() => discover.mutate(integration.id)}>
                             {t('discover')}
                           </button>
                           <button type="button" className="btn-secondary text-xs"
                                   disabled={integration.mappingApproved
                                             || !integration.capabilityReport}
                                   onClick={() => approveMapping.mutate(integration.id)}>
                             {integration.mappingApproved ? 'Mapping approved' : t('approveMapping')}
                           </button>
                           <button type="button" className="btn-secondary text-xs"
                                   onClick={() => toggle.mutate({
                                     id: integration.id,
                                     body: { enabled: !integration.enabled, isPrimary: true },
                                   })}>
                             {integration.enabled ? 'Disable' : 'Enable'}
                           </button>
                           <button type="button" className="btn-primary text-xs"
                                   disabled={!integration.mappingApproved}
                                   onClick={() => setPreviewFor(integration)}>
                             {t('publish')}
                           </button>
                         </div>
                       }>
                {integration.capabilityReport ? (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2 text-xs">
                      <Badge tone="muted">
                        Discovered {formatDateTime(integration.capabilityReport.discoveredAt)}
                      </Badge>
                      <Badge tone="muted">
                        {integration.capabilityReport.projects.length} project(s)
                      </Badge>
                      <Badge tone="muted">
                        {integration.capabilityReport.itemTypes.length} item type(s)
                      </Badge>
                      <Badge tone={integration.capabilityReport.supportsWorklogs
                        ? 'good' : 'warning'}>
                        worklogs {integration.capabilityReport.supportsWorklogs
                          ? 'supported' : 'unsupported'}
                      </Badge>
                    </div>

                    {integration.capabilityReport.limitations.length ? (
                      <div>
                        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide
                                       text-ink-500">{t('limitations')}</h3>
                        <ul className="space-y-1">
                          {integration.capabilityReport.limitations.map((limitation) => (
                            <li key={limitation}>
                              <Note tone="warning">{limitation}</Note>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                      <div>
                        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide
                                       text-ink-500">Type mappings</h3>
                        <Table
                          rows={integration.typeMappings}
                          rowKey={(row) => row.canonicalType}
                          columns={[
                            { key: 'canonical', header: 'Canonical',
                              render: (row) => row.canonicalType },
                            { key: 'external', header: 'External',
                              render: (row) => row.externalType ?? '—' },
                            { key: 'strategy', header: 'Strategy',
                              render: (row) => (
                                <Badge tone={row.strategy === 'native' ? 'good'
                                  : row.strategy === 'unsupported' ? 'critical' : 'warning'}>
                                  {row.strategy}
                                </Badge>
                              ) },
                          ]} />
                      </div>
                      <div>
                        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide
                                       text-ink-500">Field rules</h3>
                        <Table
                          rows={integration.fieldRules}
                          rowKey={(row) => row.canonicalField}
                          columns={[
                            { key: 'field', header: 'Field',
                              render: (row) => row.canonicalField },
                            { key: 'external', header: 'External',
                              render: (row) => row.externalField ?? '—' },
                            { key: 'ownership', header: 'Authority',
                              render: (row) => (
                                <Badge tone={row.ownership === 'three_way' ? 'warning' : 'muted'}>
                                  {row.ownership.replace('_', ' ')}
                                </Badge>
                              ) },
                            { key: 'supported', header: 'Supported',
                              render: (row) => row.supported
                                ? <Badge tone="good">yes</Badge>
                                : <Badge tone="warning">internal only</Badge> },
                          ]} />
                      </div>
                    </div>
                  </div>
                ) : (
                  <Note tone="muted">
                    Run discovery to produce a compatibility report before configuring a mapping.
                  </Note>
                )}

                <ConflictList projectId={projectId} integrationId={integration.id} />
              </Section>
            ))}
          </div>
        )
      ) : null}

      {tab === 'health' ? (
        <Section title="Connector health"
                 description="Pending jobs, dead lettered publications and open conflicts.">
          <Table
            rows={(health.data ?? []) as Record<string, string | number | boolean>[]}
            rowKey={(row) => String(row.integrationId)}
            columns={[
              { key: 'provider', header: 'Provider', render: (row) => String(row.provider) },
              { key: 'name', header: 'Connector', render: (row) => String(row.name) },
              { key: 'health', header: 'Health', render: (row) => String(row.health) },
              { key: 'pending', header: 'Pending', align: 'right',
                render: (row) => String(row.pendingJobs) },
              { key: 'dead', header: 'Dead lettered', align: 'right',
                render: (row) => String(row.deadLettered) },
              { key: 'conflicts', header: 'Conflicts', align: 'right',
                render: (row) => String(row.openConflicts) },
              { key: 'sync', header: 'Last sync',
                render: (row) => row.lastSyncAt ? formatDateTime(String(row.lastSyncAt)) : '—' },
            ]} />
        </Section>
      ) : null}

      <CreateConnectorModal open={creating} onClose={() => setCreating(false)}
                            onCreate={(body) => create.mutate(body)}
                            busy={create.isPending} error={create.error} />

      {previewFor ? (
        <PublishModal projectId={projectId} integration={previewFor}
                      onClose={() => setPreviewFor(null)} />
      ) : null}
    </>
  )
}

function ConflictList({ projectId, integrationId }: {
  projectId: string; integrationId: string
}) {
  const queryClient = useQueryClient()
  const conflicts = useQuery({
    queryKey: ['conflicts', projectId, integrationId],
    queryFn: () => api<{ id: string; externalId?: string | null
                         conflicts: { field: string; internalValue: unknown
                                      externalValue: unknown; commonValue: unknown }[] }[]>(
      `/projects/${projectId}/integrations/${integrationId}/conflicts`),
  })
  const resolve = useMutation({
    mutationFn: ({ id, resolutions }: { id: string; resolutions: Record<string, string> }) =>
      api(`/projects/${projectId}/integrations/conflicts/resolve`, {
        method: 'POST', body: { syncEventId: id, resolutions },
      }),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['conflicts', projectId, integrationId] }),
  })

  if (!conflicts.data?.length) return null

  return (
    <div className="mt-4">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-500">
        Field level conflicts
      </h3>
      <div className="space-y-2">
        {conflicts.data.map((event) => (
          <div key={event.id} className="rounded border border-amber-200 bg-amber-50 p-2">
            <p className="text-xs text-amber-900">External item {event.externalId}</p>
            {event.conflicts.map((conflict) => (
              <div key={conflict.field}
                   className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                <strong>{conflict.field}</strong>
                <span>internal: {String(conflict.internalValue)}</span>
                <span>external: {String(conflict.externalValue)}</span>
                <span className="text-ink-500">last agreed: {String(conflict.commonValue)}</span>
                <button type="button" className="btn-secondary text-xs"
                        onClick={() => resolve.mutate({
                          id: event.id, resolutions: { [conflict.field]: 'internal' } })}>
                  Keep internal
                </button>
                <button type="button" className="btn-secondary text-xs"
                        onClick={() => resolve.mutate({
                          id: event.id, resolutions: { [conflict.field]: 'external' } })}>
                  Take external
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function PublishModal({ projectId, integration, onClose }: {
  projectId: string; integration: Integration; onClose: () => void
}) {
  const [eventId, setEventId] = useState('')

  const events = useQuery({
    queryKey: ['approval-events', projectId],
    queryFn: () => api<ApprovalEvent[]>(`/projects/${projectId}/approvals/events`),
  })
  const preview = useQuery({
    queryKey: ['publication-preview', projectId, integration.id, eventId],
    queryFn: () => api<PublicationPreview>(
      `/projects/${projectId}/integrations/${integration.id}/preview`,
      { query: { approvalEventId: eventId } }),
    enabled: Boolean(eventId),
    retry: false,
  })
  const publish = useMutation({
    mutationFn: () => api(`/projects/${projectId}/integrations/${integration.id}/publish`, {
      method: 'POST',
      body: { approvalEventId: eventId, itemIds: [] },
      idempotencyKey: `publish-${eventId}`,
    }),
    onSuccess: onClose,
  })

  const approved = (events.data ?? []).filter(
    (event) => event.decision === 'approve' && event.committed && !event.revoked)

  return (
    <Modal open wide title={`Publish to ${integration.name}`} onClose={onClose}
           footer={
             <>
               <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
               <button type="button" className="btn-primary"
                       disabled={!eventId || publish.isPending}
                       onClick={() => publish.mutate()}>Enqueue publication</button>
             </>
           }>
      <div className="space-y-3">
        <Field label="Approved bundle"
               hint="Only committed, non revoked approvals may be published">
          <select className="input" value={eventId}
                  onChange={(event) => setEventId(event.target.value)}>
            <option value="">Select an approval…</option>
            {approved.map((event) => (
              <option key={event.id} value={event.id}>
                {formatDateTime(event.decidedAt)} — {event.entries.length} version(s)
              </option>
            ))}
          </select>
        </Field>

        {preview.isLoading ? <Spinner /> : null}
        {preview.error ? <ErrorBanner error={preview.error} /> : null}
        {preview.data ? (
          <>
            {preview.data.hierarchyNote ? (
              <Note tone="warning">{preview.data.hierarchyNote}</Note>
            ) : null}
            {preview.data.informationLoss ? (
              <Note tone="warning">
                Some fields cannot be carried by this destination. They stay in the internal
                canonical model and are listed per row below.
              </Note>
            ) : null}
            <Table
              rows={preview.data.rows}
              rowKey={(row) => row.internalId}
              columns={[
                { key: 'id', header: 'ID', render: (row) => row.stableId },
                { key: 'title', header: 'Title', render: (row) => row.title },
                { key: 'type', header: 'Mapping',
                  render: (row) => `${row.canonicalType} → ${row.externalType ?? 'unsupported'}` },
                { key: 'action', header: 'Action',
                  render: (row) => <Badge tone={row.action === 'create' ? 'info' : 'muted'}>
                    {row.action}</Badge> },
                { key: 'unsupported', header: 'Stays internal',
                  render: (row) => row.unsupportedFields.length
                    ? <span className="text-xs text-amber-700">
                        {row.unsupportedFields.join(', ')}
                      </span>
                    : '—' },
              ]} />
            {preview.data.blocked.length ? (
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Not published
                </h3>
                <ul className="space-y-1 text-xs text-ink-600">
                  {preview.data.blocked.map((row, index) => (
                    <li key={index}>{row.stableId}: {row.reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : null}
        {publish.error ? <ErrorBanner error={publish.error} /> : null}
      </div>
    </Modal>
  )
}

function CreateConnectorModal({ open, onClose, onCreate, busy, error }: {
  open: boolean
  onClose: () => void
  onCreate: (body: Record<string, unknown>) => void
  busy: boolean
  error: unknown
}) {
  const [provider, setProvider] = useState('jira')
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [projectKey, setProjectKey] = useState('')
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')

  return (
    <Modal open={open} title="Add connector" onClose={onClose}
           footer={
             <>
               <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
               <button type="button" className="btn-primary" disabled={busy || !name}
                       onClick={() => onCreate({
                         provider, name, baseUrl, externalProjectKey: projectKey,
                         credential: token
                           ? { baseUrl, email, token, project: projectKey }
                           : {},
                       })}>Add connector</button>
             </>
           }>
      <div className="space-y-3">
        <Field label="Provider">
          <select className="input" value={provider}
                  onChange={(event) => setProvider(event.target.value)}>
            {PROVIDERS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Name"><input className="input" value={name}
          onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="Base URL" hint="For example https://company.atlassian.net">
          <input className="input" value={baseUrl}
                 onChange={(event) => setBaseUrl(event.target.value)} />
        </Field>
        <Field label="External project key or id">
          <input className="input" value={projectKey}
                 onChange={(event) => setProjectKey(event.target.value)} />
        </Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Account email"><input className="input" value={email}
            onChange={(event) => setEmail(event.target.value)} /></Field>
          <Field label="API token">
            <input className="input" type="password" value={token}
                   onChange={(event) => setToken(event.target.value)} />
          </Field>
        </div>
        <Note tone="muted">
          Credentials are encrypted on company infrastructure, referenced by id elsewhere,
          and never enter an AI context. Without credentials, discovery returns the
          provider's documented model rather than your tenant.
        </Note>
        {error ? <ErrorBanner error={error} /> : null}
      </div>
    </Modal>
  )
}
