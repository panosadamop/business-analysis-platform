/** Screen 7 — approval inbox: subtree manifest, diff, blockers, waivers, cascade. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from '../lib/api'
import { useI18n } from '../i18n'
import {
  Badge, EmptyState, ErrorBanner, Modal, Note, PageHeader, Section, SeverityBadge,
  Spinner, StateBadge, Table, Tabs, formatDateTime,
} from '../components/ui'
import type { ApprovalEvent, ApprovalManifest, Blocker } from '../types'

interface Candidate {
  itemId: string
  stableId: string
  type: string
  title: string
  currentVersion: number
  approvedVersion?: number | null
  requiresReapproval: boolean
  stale: boolean
}

export function ApprovalsPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('inbox')
  const [manifest, setManifest] = useState<ApprovalManifest | null>(null)
  const [waivers, setWaivers] = useState<Record<string, string>>({})
  const [conflict, setConflict] = useState<ApiError | null>(null)

  const inbox = useQuery({
    queryKey: ['approval-inbox', projectId],
    queryFn: () => api<{ candidates: Candidate[]; pendingCount: number; canDecide: boolean
                         canWaive: boolean }>(`/projects/${projectId}/approvals/inbox`),
  })
  const events = useQuery({
    queryKey: ['approval-events', projectId],
    queryFn: () => api<ApprovalEvent[]>(`/projects/${projectId}/approvals/events`),
  })

  const preview = useMutation({
    mutationFn: (rootId: string) =>
      api<ApprovalManifest>(`/projects/${projectId}/approvals/preview/${rootId}`,
                            { method: 'POST' }),
    onSuccess: (data) => {
      setManifest(data)
      setWaivers({})
      setConflict(null)
    },
  })

  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject') =>
      api<ApprovalEvent>(`/projects/${projectId}/approvals/decisions`, {
        method: 'POST',
        body: {
          manifestId: manifest!.id,
          manifestHash: manifest!.manifestHash,
          decision,
          waivers: Object.entries(waivers).map(([key, rationale]) => {
            const [blockerKind, targetId] = key.split('::')
            return { blockerKind, targetId: targetId || null, rationale }
          }),
        },
      }),
    onSuccess: () => {
      setManifest(null)
      void queryClient.invalidateQueries({ queryKey: ['approval-inbox', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['approval-events', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['backlog-tree', projectId] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.isVersionConflict) setConflict(error)
    },
  })

  const revoke = useMutation({
    mutationFn: ({ eventId, reason }: { eventId: string; reason: string }) =>
      api(`/projects/${projectId}/approvals/events/${eventId}/revoke`, {
        method: 'POST', body: { reason, itemIds: [] },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['approval-events', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['approval-inbox', projectId] })
    },
  })

  const unresolved = (manifest?.blockers ?? []).filter(
    (blocker) => blocker.severity === 'critical'
      && !waivers[`${blocker.kind}::${blocker.targetId ?? ''}`])

  return (
    <>
      <PageHeader title={t('approvalsTitle')} subtitle={t('approvalsSubtitle')} />

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: 'inbox', label: 'Awaiting decision', count: inbox.data?.pendingCount },
        { key: 'history', label: 'Approval history', count: events.data?.length },
      ]} />

      {tab === 'inbox' ? (
        inbox.isLoading ? <Spinner /> :
        !inbox.data?.candidates.length ? (
          <EmptyState title="Nothing is waiting for approval"
                      hint="Items appear here when they have never been approved or when a descendant changed after approval." />
        ) : (
          <Section title="Candidates"
                   description="Approving a parent approves its current descendant versions through a recorded cascade.">
            <Table
              rows={inbox.data.candidates}
              rowKey={(row) => row.itemId}
              columns={[
                { key: 'id', header: 'ID', render: (row) => row.stableId },
                { key: 'type', header: 'Type', render: (row) => row.type },
                { key: 'title', header: 'Title', render: (row) => row.title },
                { key: 'version', header: 'Version', align: 'right',
                  render: (row) => (
                    <span>
                      v{row.currentVersion}
                      {row.approvedVersion
                        ? <span className="text-ink-500"> (approved v{row.approvedVersion})</span>
                        : null}
                    </span>
                  ) },
                { key: 'flags', header: 'Flags',
                  render: (row) => (
                    <div className="flex flex-wrap gap-1">
                      {row.requiresReapproval
                        ? <Badge tone="warning">needs renewal</Badge> : null}
                      {row.stale ? <Badge tone="warning">stale evidence</Badge> : null}
                      {!row.approvedVersion ? <Badge tone="muted">never approved</Badge> : null}
                    </div>
                  ) },
                { key: 'actions', header: '', align: 'right',
                  render: (row) => (
                    <button type="button" className="btn-secondary text-xs"
                            disabled={preview.isPending}
                            onClick={() => preview.mutate(row.itemId)}>
                      {t('previewBundle')}
                    </button>
                  ) },
              ]} />
            {preview.error ? <div className="mt-3"><ErrorBanner error={preview.error} /></div> : null}
          </Section>
        )
      ) : null}

      {tab === 'history' ? (
        <Section title="Approval history"
                 description="Every decision records the exact versions, explicit versus inherited approval and any waivers.">
          <div className="space-y-3">
            {(events.data ?? []).map((event) => (
              <article key={event.id} className="rounded-lg border border-ink-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={event.decision === 'approve' ? 'good' : 'critical'}>
                    {event.decision}
                  </Badge>
                  {event.committed ? null : <Badge tone="warning">not committed</Badge>}
                  {event.revoked ? <Badge tone="critical">revoked</Badge> : null}
                  <span className="text-sm text-ink-700">{event.rootType} {event.rootId.slice(0, 8)}</span>
                  <span className="text-xs text-ink-500">{formatDateTime(event.decidedAt)}</span>
                </div>
                <p className="mt-1 text-xs text-ink-600">
                  {event.entries.length} version(s):
                  {' '}{event.entries.filter((entry) => !entry.inherited).length} explicit,
                  {' '}{event.entries.filter((entry) => entry.inherited).length} inherited,
                  {' '}{event.entries.filter((entry) => entry.referenceOnly).length} reference only.
                  {event.publishedTargets.length
                    ? ` Published to ${event.publishedTargets.length} destination(s).`
                    : ''}
                </p>
                {event.waivers.length ? (
                  <ul className="mt-2 space-y-1">
                    {event.waivers.map((waiver, index) => (
                      <li key={index} className="text-xs text-amber-700">
                        Waived {waiver.blockerKind}: {waiver.rationale}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {!event.revoked && event.committed ? (
                  <button type="button" className="btn-danger mt-2 text-xs"
                          onClick={() => {
                            const reason = window.prompt('Reason for revocation')
                            if (reason) revoke.mutate({ eventId: event.id, reason })
                          }}>
                    {t('revoke')}
                  </button>
                ) : null}
              </article>
            ))}
            {!events.data?.length ? (
              <p className="py-6 text-center text-sm text-ink-500">No decisions recorded</p>
            ) : null}
          </div>
        </Section>
      ) : null}

      <Modal
        open={Boolean(manifest)}
        wide
        title={manifest ? `Approval bundle — ${manifest.rootTitle}` : 'Approval bundle'}
        onClose={() => setManifest(null)}
        footer={
          <>
            <button type="button" className="btn-secondary"
                    onClick={() => setManifest(null)}>{t('cancel')}</button>
            <button type="button" className="btn-danger" disabled={decide.isPending}
                    onClick={() => decide.mutate('reject')}>{t('rejectBundle')}</button>
            <button type="button" className="btn-primary"
                    disabled={decide.isPending || unresolved.length > 0
                              || !inbox.data?.canDecide}
                    onClick={() => decide.mutate('approve')}>
              {t('approveBundle')}
            </button>
          </>
        }>
        {manifest ? (
          <div className="space-y-4">
            {conflict ? (
              <Note tone="critical">
                {t('approvalConflict')} Re-open the preview to see the refreshed manifest.
              </Note>
            ) : null}

            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              {Object.entries(manifest.counts).map(([key, value]) => (
                <div key={key} className="rounded border border-ink-200 px-2 py-1">
                  <p className="text-xs text-ink-500">{key.replace(/_/g, ' ')}</p>
                  <p className="text-sm font-semibold tabular-nums">{value}</p>
                </div>
              ))}
            </div>

            <div className="rounded-lg border border-ink-200 p-3 text-sm">
              <p className="font-medium text-ink-900">Estimate totals</p>
              <p className="text-ink-600">
                {String(manifest.estimateTotals.detailedHours ?? 0)} person hours
                {manifest.estimateTotals.storyPoints
                  ? ` · ${manifest.estimateTotals.storyPoints} story points` : ''}
                {' '}· {String(manifest.estimateTotals.itemsWithEstimate ?? 0)} of
                {' '}{String(manifest.estimateTotals.itemsTotal ?? 0)} items estimated
              </p>
            </div>

            {manifest.blockers.length ? (
              <section>
                <h3 className="mb-1 text-sm font-semibold text-ink-900">{t('blockers')}</h3>
                <ul className="space-y-2">
                  {manifest.blockers.map((blocker, index) => (
                    <BlockerRow key={index} blocker={blocker}
                                canWaive={Boolean(inbox.data?.canWaive)}
                                rationale={waivers[`${blocker.kind}::${blocker.targetId ?? ''}`]}
                                onWaive={(rationale) => setWaivers((current) => ({
                                  ...current,
                                  [`${blocker.kind}::${blocker.targetId ?? ''}`]: rationale,
                                }))} />
                  ))}
                </ul>
              </section>
            ) : (
              <Note tone="muted">No blockers. Every quality gate passes for this bundle.</Note>
            )}

            {manifest.diff ? (
              <section>
                <h3 className="mb-1 text-sm font-semibold text-ink-900">
                  {t('diffVsPrevious')}
                </h3>
                <p className="text-xs text-ink-600">
                  {manifest.diff.added.length} added · {manifest.diff.changed.length} changed ·
                  {' '}{manifest.diff.removed.length} removed ·
                  {' '}{manifest.diff.unchangedCount} unchanged
                </p>
              </section>
            ) : null}

            <section>
              <h3 className="mb-1 text-sm font-semibold text-ink-900">{t('manifest')}</h3>
              <Table
                rows={manifest.entries}
                rowKey={(row) => `${row.itemId}-${row.versionId}`}
                columns={[
                  { key: 'id', header: 'ID', render: (row) => row.stableId },
                  { key: 'type', header: 'Type', render: (row) => row.itemType },
                  { key: 'title', header: 'Title', render: (row) => row.title },
                  { key: 'version', header: 'Version', align: 'right',
                    render: (row) => `v${row.version}` },
                  { key: 'state', header: 'State',
                    render: (row) => <StateBadge state={row.state} /> },
                  { key: 'mode', header: 'Approval',
                    render: (row) => row.referenceOnly
                      ? <Badge tone="muted">{t('referenceOnly')}</Badge>
                      : row.inherited
                        ? <Badge tone="info">{t('inherited')}</Badge>
                        : <Badge tone="good">{t('explicit')}</Badge> },
                ]} />
            </section>

            <Note tone="muted">
              Manifest hash {manifest.manifestHash.slice(0, 16)}… — if any included version
              changes before you submit, the decision fails atomically and nothing is approved.
            </Note>

            {decide.error && !conflict ? <ErrorBanner error={decide.error} /> : null}
            {conflict ? <ErrorBanner error={conflict} /> : null}
          </div>
        ) : null}
      </Modal>
    </>
  )
}

function BlockerRow({ blocker, canWaive, rationale, onWaive }: {
  blocker: Blocker
  canWaive: boolean
  rationale?: string
  onWaive: (rationale: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(rationale ?? '')

  return (
    <li className="rounded border border-ink-200 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={blocker.severity} />
        <Badge tone="muted">{blocker.kind.replace(/_/g, ' ')}</Badge>
        <span className="text-sm text-ink-800">{blocker.message}</span>
        {rationale ? <Badge tone="good">waived</Badge> : null}
      </div>
      {blocker.targetTitle ? (
        <p className="mt-0.5 text-xs text-ink-500">{blocker.targetTitle}</p>
      ) : null}
      {rationale ? (
        <p className="mt-1 text-xs text-amber-700">Rationale: {rationale}</p>
      ) : blocker.waivable && canWaive ? (
        editing ? (
          <div className="mt-2 flex gap-2">
            <input className="input flex-1" value={draft} placeholder="Recorded rationale"
                   aria-label="Waiver rationale"
                   onChange={(event) => setDraft(event.target.value)} />
            <button type="button" className="btn-secondary text-xs"
                    disabled={!draft.trim()}
                    onClick={() => { onWaive(draft.trim()); setEditing(false) }}>
              Record waiver
            </button>
          </div>
        ) : (
          <button type="button" className="btn-ghost mt-1 px-0 text-xs"
                  onClick={() => setEditing(true)}>Waive with rationale</button>
        )
      ) : !blocker.waivable ? (
        <p className="mt-1 text-xs text-red-700">This blocker cannot be waived.</p>
      ) : null}
    </li>
  )
}
