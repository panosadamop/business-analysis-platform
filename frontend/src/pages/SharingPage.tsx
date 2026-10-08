/** Screen 13 (internal side) — share approved versions with a client reviewer. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import {
  Badge, ErrorBanner, Field, Modal, Note, PageHeader, Section, Spinner, Table,
  formatDateTime,
} from '../components/ui'
import type { BacklogNode, ShareGrant } from '../types'

export function SharingPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)

  const grants = useQuery({
    queryKey: ['shares', projectId],
    queryFn: () => api<ShareGrant[]>(`/projects/${projectId}/shares`),
  })
  const tree = useQuery({
    queryKey: ['backlog-tree', projectId],
    queryFn: () => api<BacklogNode[]>(`/projects/${projectId}/backlog/tree`),
  })

  const revoke = useMutation({
    mutationFn: (id: string) =>
      api(`/projects/${projectId}/shares/${id}/revoke`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shares', projectId] }),
  })

  // The screen keeps its heading (and so its document title) while it loads or fails.
  const loadingHeader = <PageHeader title={t('navClient')} subtitle={t('clientSubtitle')} />
  if (grants.isLoading) return <>{loadingHeader}<Spinner /></>
  if (grants.error) return <>{loadingHeader}<ErrorBanner error={grants.error} /></>

  return (
    <>
      <PageHeader title={t('navClient')} subtitle={t('clientSubtitle')}
                  actions={<button type="button" className="btn-primary"
                                   onClick={() => setCreating(true)}>{t('shareVersions')}</button>} />

      <div className="mb-4">
        <Note tone="muted">
          Sharing defaults to immutable approved versions. Source files, recordings,
          internal notes, rates and AI diagnostics are excluded unless deliberately allowed.
          Revocation prevents future access but cannot recall files already downloaded.
        </Note>
      </div>

      <Section title="Share grants">
        <Table
          rows={grants.data ?? []}
          rowKey={(row) => row.id}
          empty="Nothing has been shared with a client yet"
          columns={[
            { key: 'audience', header: t('shared'),
              render: (row) => (
                <div>
                  <p className="font-medium text-ink-900">{row.audienceEmail}</p>
                  {row.label ? <p className="text-xs text-ink-500">{row.label}</p> : null}
                </div>
              ) },
            { key: 'versions', header: 'Versions',
              render: (row) => (
                <div className="flex flex-wrap gap-1">
                  {row.versions.map((version) => (
                    <Badge key={version.itemId} tone={version.draft ? 'warning' : 'muted'}>
                      {version.stableId} v{version.version}{version.draft ? ' draft' : ''}
                    </Badge>
                  ))}
                </div>
              ) },
            { key: 'permissions', header: 'Permissions',
              render: (row) => (
                <div className="flex flex-wrap gap-1">
                  {row.allowAcceptance ? <Badge tone="info">acceptance</Badge> : null}
                  {row.allowDownload ? <Badge tone="info">download</Badge> : null}
                  {row.includeDrafts ? <Badge tone="warning">drafts</Badge> : null}
                </div>
              ) },
            { key: 'expiry', header: 'Expires',
              render: (row) => formatDateTime(row.expiresAt) },
            { key: 'status', header: 'Status',
              render: (row) => row.revokedAt
                ? <Badge tone="critical">revoked</Badge>
                : <Badge tone="good">active</Badge> },
            { key: 'actions', header: '', align: 'right',
              render: (row) => row.revokedAt ? null : (
                <button type="button" className="btn-danger text-xs"
                        onClick={() => revoke.mutate(row.id)}>Revoke</button>
              ) },
          ]} />
      </Section>

      <ShareModal open={creating} onClose={() => setCreating(false)} projectId={projectId}
                  tree={tree.data ?? []} />
    </>
  )
}

function ShareModal({ open, onClose, projectId, tree }: {
  open: boolean; onClose: () => void; projectId: string; tree: BacklogNode[]
}) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [label, setLabel] = useState('')
  const [itemIds, setItemIds] = useState<string[]>([])
  const [allowAcceptance, setAllowAcceptance] = useState(false)
  const [includeDrafts, setIncludeDrafts] = useState(false)
  const [includeQuestions, setIncludeQuestions] = useState(true)
  const [includeTests, setIncludeTests] = useState(false)

  const create = useMutation({
    mutationFn: () => api(`/projects/${projectId}/shares`, {
      method: 'POST',
      body: { audienceEmail: email, label, itemIds, allowAcceptance, includeDrafts,
              includeQuestions, includeTests },
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['shares', projectId] })
      onClose()
    },
  })

  const flat: BacklogNode[] = []
  const walk = (nodes: BacklogNode[]) => nodes.forEach((node) => {
    flat.push(node)
    walk(node.children)
  })
  walk(tree)

  return (
    <Modal open={open} wide title="Share versions with a client" onClose={onClose}
           footer={
             <>
               <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
               <button type="button" className="btn-primary"
                       disabled={create.isPending || !email || !itemIds.length}
                       onClick={() => create.mutate()}>Create grant</button>
             </>
           }>
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Client email"><input className="input" value={email}
            onChange={(event) => setEmail(event.target.value)} /></Field>
          <Field label="Label"><input className="input" value={label}
            onChange={(event) => setLabel(event.target.value)} /></Field>
        </div>

        <fieldset>
          <legend className="label mb-1">Items</legend>
          <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-ink-200 p-2">
            {flat.map((node) => (
              <label key={node.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={itemIds.includes(node.id)}
                       onChange={(event) => setItemIds(event.target.checked
                         ? [...itemIds, node.id]
                         : itemIds.filter((id) => id !== node.id))} />
                <Badge tone="muted">{node.type}</Badge>
                <span className="text-ink-500">{node.stableId}</span>
                <span className="flex-1 truncate">{node.title}</span>
                {node.approvedVersion
                  ? <Badge tone="good">approved v{node.approvedVersion}</Badge>
                  : <Badge tone="warning">draft only</Badge>}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Checkbox label="Allow client acceptance" checked={allowAcceptance}
                    onChange={setAllowAcceptance}
                    hint="Business acceptance is recorded separately from internal approval" />
          <Checkbox label="Include draft versions" checked={includeDrafts}
                    onChange={setIncludeDrafts}
                    hint="Drafts are labelled as such in the client workspace" />
          <Checkbox label="Include client visible questions" checked={includeQuestions}
                    onChange={setIncludeQuestions} />
          <Checkbox label="Include linked tests" checked={includeTests}
                    onChange={setIncludeTests} />
        </div>

        {create.error ? <ErrorBanner error={create.error} /> : null}
      </div>
    </Modal>
  )
}

function Checkbox({ label, hint, checked, onChange }: {
  label: string; hint?: string; checked: boolean; onChange: (value: boolean) => void
}) {
  return (
    <label className="flex items-start gap-2 rounded-lg border border-ink-200 px-3 py-2">
      <input type="checkbox" className="mt-0.5" checked={checked}
             onChange={(event) => onChange(event.target.checked)} />
      <span>
        <span className="block text-sm font-medium text-ink-800">{label}</span>
        {hint ? <span className="block text-xs text-ink-500">{hint}</span> : null}
      </span>
    </label>
  )
}
