/** Screen 5 — backlog tree with detail, criteria, tests, estimates and rollups. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import { AddEvidenceLinkModal } from '../components/entry-forms'
import {
  Badge, EmptyState, ErrorBanner, Field, Modal, Note, PageHeader, ProvenanceBadge,
  Section, Spinner, StateBadge, Table, formatDateTime, money,
} from '../components/ui'
import type { BacklogNode, ItemDetail, SourceView } from '../types'

const TYPE_TONE: Record<string, string> = {
  epic: 'info', feature: 'neutral', story: 'muted', task: 'muted',
}

export function BacklogPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const [selected, setSelected] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const tree = useQuery({
    queryKey: ['backlog-tree', projectId],
    queryFn: () => api<BacklogNode[]>(`/projects/${projectId}/backlog/tree`),
  })
  const dependencies = useQuery({
    queryKey: ['dependencies', projectId],
    queryFn: () => api<{ cycles: string[][]; unowned: Record<string, unknown>[] }>(
      `/projects/${projectId}/backlog/dependencies`),
  })

  // The screen keeps its heading (and so its document title) while it loads or fails.
  const loadingHeader = <PageHeader title={t('backlogTitle')} subtitle={t('backlogSubtitle')} />
  if (tree.isLoading) return <>{loadingHeader}<Spinner /></>
  if (tree.error) return <>{loadingHeader}<ErrorBanner error={tree.error} onRetry={tree.refetch} /></>

  const roots = tree.data ?? []

  return (
    <>
      <PageHeader title={t('backlogTitle')} subtitle={t('backlogSubtitle')}
                  actions={<button type="button" className="btn-primary"
                                   onClick={() => setCreating(true)}>Add item</button>} />

      {dependencies.data?.cycles.length ? (
        <div className="mb-4">
          <Note tone="critical">
            {dependencies.data.cycles.length} dependency cycle(s) detected:
            {' '}{dependencies.data.cycles.map((cycle) => cycle.join(' → ')).join('; ')}
          </Note>
        </div>
      ) : null}

      {roots.length === 0 ? (
        <EmptyState title="The backlog is empty"
                    hint="Run the analysis workflow to propose a hierarchy from the evidence, or add items manually." />
      ) : (
        <Section title="Hierarchy"
                 description="Project → epic → feature → story. Rollups exclude the parent's initial rough estimate.">
          <ul className="space-y-1">
            {roots.map((node) => (
              <TreeNode key={node.id} node={node} depth={0} onSelect={setSelected} />
            ))}
          </ul>
        </Section>
      )}

      {selected ? (
        <ItemDrawer projectId={projectId} itemId={selected}
                    onClose={() => setSelected(null)} />
      ) : null}

      <CreateItemModal open={creating} onClose={() => setCreating(false)}
                       projectId={projectId} tree={roots} />
    </>
  )
}

function TreeNode({ node, depth, onSelect }: {
  node: BacklogNode; depth: number; onSelect: (id: string) => void
}) {
  const [open, setOpen] = useState(depth < 2)
  return (
    <li>
      <div className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-ink-50"
           style={{ paddingLeft: `${depth * 18 + 8}px` }}>
        {node.children.length ? (
          <button type="button" className="text-xs text-ink-500"
                  aria-expanded={open} onClick={() => setOpen(!open)}
                  aria-label={`${open ? 'Collapse' : 'Expand'} ${node.stableId}`}>
            <span aria-hidden>{open ? '▾' : '▸'}</span>
          </button>
        ) : <span className="w-3" />}
        <Badge tone={TYPE_TONE[node.type]}>{node.type}</Badge>
        <button type="button" className="flex-1 truncate text-left text-sm text-ink-900
                                          hover:underline"
                onClick={() => onSelect(node.id)}>
          <span className="text-ink-500">{node.stableId}</span> {node.title}
        </button>
        <div className="hidden shrink-0 items-center gap-2 sm:flex">
          {node.stale ? <Badge tone="warning" icon="⚠">stale</Badge> : null}
          {node.requiresReapproval ? (
            <Badge tone="warning">needs re-approval</Badge>
          ) : null}
          <StateBadge state={node.state} />
          <span className="w-16 text-right text-xs tabular-nums text-ink-600">
            {node.rollupHours ? `${node.rollupHours} h` : '—'}
          </span>
          <span className="w-10 text-right text-xs tabular-nums text-ink-500">
            {node.storyPoints ?? '—'}
          </span>
          <span className="w-16 text-right text-xs text-ink-500">
            {node.criteriaCount} AC · {node.testCount} T
          </span>
        </div>
      </div>
      {open && node.children.length ? (
        <ul className="space-y-1">
          {node.children.map((child) => (
            <TreeNode key={child.id} node={child} depth={depth + 1} onSelect={onSelect} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function ItemDrawer({ projectId, itemId, onClose }: {
  projectId: string; itemId: string; onClose: () => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [linking, setLinking] = useState(false)

  const sources = useQuery({
    queryKey: ['sources', projectId],
    queryFn: () => api<SourceView[]>(`/projects/${projectId}/sources`),
  })
  const linkEvidence = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/evidence-links`, {
        method: 'POST', body: { ...body, targetId: itemId },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['item', projectId, itemId] })
      void queryClient.invalidateQueries({ queryKey: ['traceability', projectId] })
      setLinking(false)
    },
  })

  const detail = useQuery({
    queryKey: ['item', projectId, itemId],
    queryFn: () => api<ItemDetail>(`/projects/${projectId}/backlog/items/${itemId}`),
  })

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/backlog/items/${itemId}`, { method: 'PATCH', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['item', projectId, itemId] })
      void queryClient.invalidateQueries({ queryKey: ['backlog-tree', projectId] })
      setEditing(false)
    },
  })

  const estimate = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/backlog/items/${itemId}/estimate`, {
        method: 'POST', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['item', projectId, itemId] })
      void queryClient.invalidateQueries({ queryKey: ['backlog-tree', projectId] })
    },
  })

  const data = detail.data

  return (
    <Modal open wide title={data ? `${data.item.stableId} — ${data.item.title}` : 'Item'}
           onClose={onClose}>
      {detail.isLoading ? <Spinner /> : null}
      {detail.error ? <ErrorBanner error={detail.error} /> : null}
      {data ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={data.item.state} />
            <Badge tone="muted">v{data.item.currentVersion}</Badge>
            {data.item.approvedVersion ? (
              <Badge tone="good">approved v{data.item.approvedVersion}</Badge>
            ) : <Badge tone="warning">not approved</Badge>}
            {data.item.requiresReapproval ? (
              <Badge tone="warning">parent bundle needs renewed approval</Badge>
            ) : null}
            <ProvenanceBadge provenance={data.version.provenance} />
            <Badge tone="muted">execution: {data.item.executionStatus.replace('_', ' ')}</Badge>
          </div>

          {data.version.generatedByRole ? (
            <Note tone="muted">
              Generated by the {data.version.generatedByRole.replace('_', ' ')} using
              {' '}{data.version.modelId}. It is a draft proposal and needs human approval.
            </Note>
          ) : null}

          {editing ? (
            <EditForm detail={data} onCancel={() => setEditing(false)}
                      onSave={(body) => update.mutate(body)}
                      busy={update.isPending} error={update.error} />
          ) : (
            <>
              <section>
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-ink-900">Description</h3>
                  <button type="button" className="btn-secondary text-xs"
                          onClick={() => setEditing(true)}>{t('edit')}</button>
                </div>
                {data.version.actor ? (
                  <p className="mb-1 text-sm text-ink-700">
                    As a <strong>{data.version.actor}</strong> I need
                    {' '}<strong>{data.version.need}</strong> so that
                    {' '}<strong>{data.version.benefit}</strong>.
                  </p>
                ) : null}
                <p className="whitespace-pre-wrap text-sm text-ink-700">
                  {data.version.description ?? '—'}
                </p>
              </section>

              <section>
                <h3 className="mb-1 text-sm font-semibold text-ink-900">
                  {t('acceptanceCriteria')}
                </h3>
                {data.version.acceptanceCriteria.length ? (
                  <ul className="space-y-1">
                    {data.version.acceptanceCriteria.map((criterion) => (
                      <li key={criterion.id}
                          className="rounded border border-ink-200 px-2 py-1 text-sm">
                        <span className="mr-2 text-xs text-ink-500">{criterion.id}</span>
                        {criterion.text}
                        {criterion.outcomeLevel ? (
                          <Badge tone="info">outcome level</Badge>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Note tone="warning">
                    No acceptance criteria. This is a critical approval blocker.
                  </Note>
                )}
              </section>

              <section>
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-ink-900">{t('citations')}</h3>
                  <button type="button" className="btn-secondary text-xs"
                          onClick={() => setLinking(true)}>Link evidence</button>
                </div>
                {data.version.citations.length ? (
                  <ul className="space-y-1 text-xs">
                    {data.version.citations.map((citation, index) => (
                      <li key={index} className="rounded bg-ink-50 px-2 py-1">
                        <code>{citation.locator.kind}:{citation.locator.value}</code>
                        {citation.quote ? ` — “${citation.quote}”` : ''}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Note tone="warning">
                    No evidence is linked. Link a source so this item is evidence backed
                    rather than an unsupported statement.
                  </Note>
                )}
              </section>

              {data.version.businessRules.length || data.version.assumptions.length ? (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {data.version.businessRules.length ? (
                    <section>
                      <h3 className="mb-1 text-sm font-semibold text-ink-900">Business rules</h3>
                      <ul className="list-disc space-y-0.5 pl-4 text-sm text-ink-700">
                        {data.version.businessRules.map((rule, index) => (
                          <li key={index}>{rule}</li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                  {data.version.assumptions.length ? (
                    <section>
                      <h3 className="mb-1 text-sm font-semibold text-ink-900">Assumptions</h3>
                      <ul className="list-disc space-y-0.5 pl-4 text-sm text-amber-800">
                        {data.version.assumptions.map((assumption, index) => (
                          <li key={index}>{assumption}</li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                </div>
              ) : null}
            </>
          )}

          <section>
            <h3 className="mb-1 text-sm font-semibold text-ink-900">{t('estimate')}</h3>
            <EstimatePanel detail={data} onSave={(body) => estimate.mutate(body)}
                           busy={estimate.isPending} />
          </section>

          <section>
            <h3 className="mb-1 text-sm font-semibold text-ink-900">{t('tests')}</h3>
            <Table rows={data.tests} rowKey={(row) => row.id}
                   empty="No tests linked. A story without a test is a critical approval blocker."
                   columns={[
                     { key: 'id', header: 'ID', render: (row) => row.stableId },
                     { key: 'title', header: 'Title', render: (row) => row.title },
                     { key: 'type', header: 'Type', render: (row) => row.testType },
                     { key: 'state', header: 'State',
                       render: (row) => <StateBadge state={row.state} /> },
                     { key: 'review', header: 'Review', render: (row) => row.reviewState },
                   ]} />
          </section>

          <section>
            <h3 className="mb-1 text-sm font-semibold text-ink-900">{t('history')}</h3>
            <ul className="space-y-1 text-xs">
              {data.history.map((entry) => (
                <li key={entry.id}
                    className="flex flex-wrap items-center gap-2 rounded border
                               border-ink-200 px-2 py-1">
                  <Badge tone="muted">v{entry.version}</Badge>
                  <StateBadge state={entry.state} />
                  <span className="text-ink-500">{formatDateTime(entry.createdAt)}</span>
                  {entry.generatedByRole ? (
                    <span className="text-ink-500">{entry.generatedByRole}</span>
                  ) : null}
                  {entry.inheritedFromEventId ? (
                    <Badge tone="info">inherited approval</Badge>
                  ) : entry.approvalEventId ? (
                    <Badge tone="good">explicitly approved</Badge>
                  ) : null}
                  {entry.changeNote ? (
                    <span className="text-ink-600">{entry.changeNote}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        </div>
      ) : null}

      <AddEvidenceLinkModal open={linking} onClose={() => setLinking(false)}
                            onCreate={(body) => linkEvidence.mutate(body)}
                            busy={linkEvidence.isPending} error={linkEvidence.error}
                            sources={sources.data ?? []} targetType="backlog_item"
                            targetLabel={data?.item.stableId ?? 'this item'} />
    </Modal>
  )
}

function EditForm({ detail, onCancel, onSave, busy, error }: {
  detail: ItemDetail
  onCancel: () => void
  onSave: (body: Record<string, unknown>) => void
  busy: boolean
  error: unknown
}) {
  const [title, setTitle] = useState(detail.version.title)
  const [description, setDescription] = useState(detail.version.description ?? '')
  const [criteria, setCriteria] = useState(
    detail.version.acceptanceCriteria.map((criterion) => criterion.text).join('\n'))
  const [note, setNote] = useState('')

  return (
    <div className="space-y-3 rounded-lg border border-brand-200 bg-brand-50/40 p-3">
      <Note tone="muted">
        Editing creates a new draft version. The approved version stays immutable and the
        parent bundle is marked as needing renewed approval.
      </Note>
      <Field label="Title"><input className="input" value={title}
        onChange={(event) => setTitle(event.target.value)} /></Field>
      <Field label="Description">
        <textarea className="input h-28" value={description}
                  onChange={(event) => setDescription(event.target.value)} />
      </Field>
      <Field label="Acceptance criteria" hint="One observable outcome per line">
        <textarea className="input h-28" value={criteria}
                  onChange={(event) => setCriteria(event.target.value)} />
      </Field>
      <Field label="Change note">
        <input className="input" value={note}
               onChange={(event) => setNote(event.target.value)} />
      </Field>
      {error ? <ErrorBanner error={error} /> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn-primary" disabled={busy}
                onClick={() => onSave({
                  title,
                  description,
                  acceptanceCriteria: criteria.split('\n').filter(Boolean).map((text, index) => ({
                    id: detail.version.acceptanceCriteria[index]?.id
                      ?? `AC-${detail.item.stableId}-${String(index + 1).padStart(2, '0')}`,
                    text,
                    outcomeLevel: ['epic', 'feature'].includes(detail.item.type),
                    provenance: 'assumption',
                  })),
                  changeNote: note,
                  expectedRev: detail.item.rev,
                })}>
          Save as new draft
        </button>
      </div>
    </div>
  )
}

function EstimatePanel({ detail, onSave, busy }: {
  detail: ItemDetail
  onSave: (body: Record<string, unknown>) => void
  busy: boolean
}) {
  const { rollup } = detail
  const [points, setPoints] = useState(detail.estimate?.storyPoints ?? '')
  const [roles, setRoles] = useState(
    (detail.estimate?.roleEfforts ?? [{ role: 'engineering', hours: 0 }])
      .map((effort) => `${effort.role}:${effort.hours}`).join(', '))
  const [overhead, setOverhead] = useState(detail.estimate?.overheadHours ?? 0)

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <Metric label="Detailed rollup" value={`${rollup.detailedHours} h`} />
        <Metric label="Person days" value={rollup.personDays} />
        <Metric label="Range" value={`${rollup.lowHours}–${rollup.highHours} h`} />
        <Metric label="Estimated cost" value={money(rollup.estimatedCost)} />
        {rollup.roughParentHours ? (
          <Metric label="Initial rough estimate (comparison only)"
                  value={`${rollup.roughParentHours} h`} />
        ) : null}
        <Metric label="Story points"
                value={rollup.storyPoints ?? '—'}
                hint={rollup.storyPointsComparable ? undefined : 'not comparable across teams'} />
        <Metric label="Children estimated"
                value={`${rollup.childrenEstimated}/${rollup.childrenTotal}`} />
        <Metric label="Overhead" value={`${rollup.ownOverheadHours} h`} />
      </dl>

      {rollup.warnings.length ? (
        <ul className="space-y-1">
          {rollup.warnings.map((warning) => (
            <li key={warning} className="text-xs text-amber-700">· {warning}</li>
          ))}
        </ul>
      ) : null}
      {detail.estimateWarnings.length ? (
        <ul className="space-y-1">
          {detail.estimateWarnings.map((warning) => (
            <li key={warning} className="text-xs text-amber-700">· {warning}</li>
          ))}
        </ul>
      ) : null}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        <Field label="Story points">
          <input className="input" value={points}
                 onChange={(event) => setPoints(event.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Role effort" hint="role:hours, comma separated">
            <input className="input" value={roles}
                   onChange={(event) => setRoles(event.target.value)} />
          </Field>
        </div>
        <Field label="Overhead hours" hint="Parent level work, excluded from children">
          <input className="input" type="number" value={overhead}
                 onChange={(event) => setOverhead(Number(event.target.value))} />
        </Field>
      </div>
      <button type="button" className="btn-secondary" disabled={busy}
              onClick={() => onSave({
                method: 'expert',
                storyPoints: points === '' ? null : Number(points),
                overheadHours: overhead,
                roleEfforts: roles.split(',').map((pair) => {
                  const [role, hours] = pair.split(':')
                  return { role: (role ?? '').trim(), hours: Number(hours ?? 0) }
                }).filter((effort) => effort.role),
              })}>
        Save estimate
      </button>
    </div>
  )
}

function Metric({ label, value, hint }: {
  label: string; value: string | number; hint?: string
}) {
  return (
    <div className="rounded border border-ink-200 px-2 py-1">
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className="text-sm font-medium tabular-nums text-ink-900">{value}</dd>
      {hint ? <p className="text-xs text-amber-700">{hint}</p> : null}
    </div>
  )
}

function CreateItemModal({ open, onClose, projectId, tree }: {
  open: boolean; onClose: () => void; projectId: string; tree: BacklogNode[]
}) {
  const queryClient = useQueryClient()
  const [type, setType] = useState<'epic' | 'feature' | 'story' | 'task'>('story')
  const [parentId, setParentId] = useState('')
  const [title, setTitle] = useState('')
  const [criteria, setCriteria] = useState('')

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/backlog/items`, { method: 'POST', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['backlog-tree', projectId] })
      onClose()
    },
  })

  const flat: BacklogNode[] = []
  const walk = (nodes: BacklogNode[]) => nodes.forEach((node) => {
    flat.push(node)
    walk(node.children)
  })
  walk(tree)
  const parentType = type === 'feature' ? 'epic' : type === 'story' ? 'feature'
    : type === 'task' ? 'story' : null

  return (
    <Modal open={open} title="Add backlog item" onClose={onClose}
           footer={
             <>
               <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
               <button type="button" className="btn-primary"
                       disabled={create.isPending || !title}
                       onClick={() => create.mutate({
                         type, parentId: parentId || null, title,
                         acceptanceCriteria: criteria.split('\n').filter(Boolean),
                       })}>Create</button>
             </>
           }>
      <div className="space-y-3">
        <Field label="Type">
          <select className="input" value={type}
                  onChange={(event) => {
                    setType(event.target.value as typeof type)
                    setParentId('')
                  }}>
            <option value="epic">Epic</option>
            <option value="feature">Feature</option>
            <option value="story">Story</option>
            <option value="task">Task</option>
          </select>
        </Field>
        {parentType ? (
          <Field label={`Parent ${parentType}`}>
            <select className="input" value={parentId}
                    onChange={(event) => setParentId(event.target.value)}>
              <option value="">Select…</option>
              {flat.filter((node) => node.type === parentType).map((node) => (
                <option key={node.id} value={node.id}>{node.stableId} — {node.title}</option>
              ))}
            </select>
          </Field>
        ) : null}
        <Field label="Title"><input className="input" value={title}
          onChange={(event) => setTitle(event.target.value)} /></Field>
        <Field label="Acceptance criteria" hint="One per line">
          <textarea className="input h-24" value={criteria}
                    onChange={(event) => setCriteria(event.target.value)} />
        </Field>
        {create.error ? <ErrorBanner error={create.error} /> : null}
      </div>
    </Modal>
  )
}
