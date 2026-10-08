/** Screen 13 (client side) — shared artifacts, comments, questions and acceptance. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import {
  Badge, EmptyState, ErrorBanner, Note, PageHeader, Section, Spinner, Table,
} from '../components/ui'
import type { ClientWorkspace } from '../types'

interface SharedProject {
  projectId: string
  name: string
  clientName?: string | null
  items: number
  allowAcceptance: boolean
  expiresAt?: string | null
}

export function ClientPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)

  const projects = useQuery({
    queryKey: ['client-projects'],
    queryFn: () => api<SharedProject[]>('/client/projects'),
  })

  const projectId = selected ?? projects.data?.[0]?.projectId ?? null

  const workspace = useQuery({
    queryKey: ['client-workspace', projectId],
    queryFn: () => api<ClientWorkspace>(`/client/projects/${projectId}/workspace`),
    enabled: Boolean(projectId),
    retry: false,
  })

  const accept = useMutation({
    mutationFn: ({ itemIds, note }: { itemIds: string[]; note?: string }) =>
      api(`/client/projects/${projectId}/acceptance`, {
        method: 'POST', body: { itemIds, accepted: true, note },
      }),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['client-workspace', projectId] }),
  })

  const comment = useMutation({
    mutationFn: ({ targetId, body }: { targetId: string; body: string }) =>
      api(`/projects/${projectId}/comments`, {
        method: 'POST',
        body: { targetType: 'backlog_item', targetId, body },
      }),
  })

  // The screen keeps its heading (and so its document title) in every state.
  const header = <PageHeader title={t('clientTitle')} subtitle={t('clientSubtitle')} />
  if (projects.isLoading) return <>{header}<Spinner /></>
  if (projects.error) return <>{header}<ErrorBanner error={projects.error} /></>
  if (!projects.data?.length) {
    return (
      <>
        {header}
        <EmptyState title="Nothing has been shared with you yet"
                    hint="Your project team shares specific approved versions with you. You will see them here." />
      </>
    )
  }

  return (
    <>
      {header}

      <div className="mb-4 flex flex-wrap gap-2">
        {projects.data.map((project) => (
          <button key={project.projectId} type="button"
                  onClick={() => setSelected(project.projectId)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm ${
                    projectId === project.projectId
                      ? 'border-brand-500 bg-brand-50'
                      : 'border-ink-200 bg-surface hover:bg-ink-50'}`}>
            <span className="block font-medium text-ink-900">{project.name}</span>
            <span className="block text-xs text-ink-500">
              {project.items} shared version(s)
              {project.allowAcceptance ? ' · acceptance enabled' : ''}
            </span>
          </button>
        ))}
      </div>

      {workspace.isLoading ? <Spinner /> : null}
      {workspace.error ? <ErrorBanner error={workspace.error} /> : null}

      {workspace.data ? (
        <div className="space-y-4">
          <Note tone="muted">{workspace.data.note}</Note>
          {workspace.data.includesDrafts ? (
            <Note tone="warning">
              This selection includes draft versions. Drafts are not approved and may change.
            </Note>
          ) : null}

          <Section title="Shared artifacts">
            <div className="space-y-3">
              {workspace.data.items.map((item) => (
                <article key={item.id} className="rounded-lg border border-ink-200 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="muted">{item.type}</Badge>
                    <span className="text-xs text-ink-500">{item.stableId}</span>
                    <Badge tone={item.isDraft ? 'warning' : 'good'}>
                      {item.isDraft ? 'draft' : `approved v${item.version}`}
                    </Badge>
                    {item.clientAccepted ? <Badge tone="good">accepted</Badge> : null}
                  </div>
                  <h3 className="mt-1 text-sm font-semibold text-ink-900">{item.title}</h3>
                  {item.description ? (
                    <p className="mt-1 whitespace-pre-wrap text-sm text-ink-700">
                      {item.description}
                    </p>
                  ) : null}
                  {item.acceptanceCriteria.length ? (
                    <ul className="mt-2 space-y-1">
                      {item.acceptanceCriteria.map((criterion) => (
                        <li key={criterion.id}
                            className="rounded bg-ink-50 px-2 py-1 text-sm text-ink-800">
                          {criterion.text}
                        </li>
                      ))}
                    </ul>
                  ) : null}

                  <form className="mt-2 flex flex-wrap gap-2"
                        onSubmit={(event) => {
                          event.preventDefault()
                          const value = new FormData(event.currentTarget).get('body')
                          if (value) comment.mutate({ targetId: item.id, body: String(value) })
                          event.currentTarget.reset()
                        }}>
                    <input name="body" className="input flex-1"
                           aria-label={`Comment on ${item.stableId}`}
                           placeholder="Comment or request a change" />
                    <button type="submit" className="btn-secondary">Send</button>
                    {workspace.data?.allowAcceptance && !item.clientAccepted ? (
                      <button type="button" className="btn-primary"
                              onClick={() => accept.mutate({ itemIds: [item.id] })}>
                        {t('accept')}
                      </button>
                    ) : null}
                  </form>
                </article>
              ))}
            </div>
          </Section>

          {workspace.data.questions.length ? (
            <Section title="Open questions for you">
              <Table
                rows={workspace.data.questions}
                rowKey={(row) => row.id}
                columns={[
                  { key: 'id', header: 'ID', render: (row) => row.stableId },
                  { key: 'title', header: 'Question',
                    render: (row) => (
                      <div>
                        <p className="font-medium text-ink-900">{row.title}</p>
                        <p className="text-xs text-ink-600">{row.detail}</p>
                      </div>
                    ) },
                  { key: 'severity', header: 'Severity', render: (row) => row.severity },
                  { key: 'status', header: 'Status', render: (row) => row.status },
                ]} />
            </Section>
          ) : null}

          {workspace.data.specifications.length ? (
            <Section title="Approved specifications">
              <div className="space-y-3">
                {workspace.data.specifications.map((spec) => (
                  <article key={spec.id}>
                    <h3 className="text-sm font-semibold text-ink-900">{spec.title}</h3>
                    {spec.body ? (
                      <p className="whitespace-pre-wrap text-sm text-ink-700">{spec.body}</p>
                    ) : null}
                  </article>
                ))}
              </div>
            </Section>
          ) : null}

          {accept.error ? <ErrorBanner error={accept.error} /> : null}
        </div>
      ) : null}
    </>
  )
}
