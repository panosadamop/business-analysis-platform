/** Screen 3 — evidence workspace: uploads, extraction, revisions and transcripts. */
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, uploadSource } from '../lib/api'
import { useI18n } from '../i18n'
import {
  Badge, EmptyState, ErrorBanner, Field, Modal, Note, PageHeader, Section, Spinner,
  Table, formatDateTime,
} from '../components/ui'
import type { SourceChunk, SourceView, TranscriptSegment } from '../types'

const KINDS = ['brief', 'meeting_notes', 'word', 'excel', 'csv', 'json', 'pdf',
               'recording', 'figma', 'adobe_xd', 'schedule', 'image', 'api_spec', 'other']

const STATUS_TONE: Record<string, string> = {
  ready: 'good', pending: 'info', extracting: 'info', failed: 'critical',
  needs_password: 'warning', unsupported: 'warning', excluded: 'muted',
  restricted: 'muted',
}

export function EvidencePage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  const sources = useQuery({
    queryKey: ['sources', projectId],
    queryFn: () => api<SourceView[]>(`/projects/${projectId}/sources`),
  })
  const limits = useQuery({
    queryKey: ['source-limits', projectId],
    queryFn: () => api<{
      maxDocumentBytes: number; maxRecordingBytes: number
      supported: Record<string, string[]>; notes: string[]
    }>(`/projects/${projectId}/sources/limits`),
  })
  const impact = useQuery({
    queryKey: ['impact', projectId],
    queryFn: () => api<{ id: string; generatedAt: string; summary: Record<string, number>;
                         affected: Record<string, unknown>[] }[]>(
      `/projects/${projectId}/sources/impact`),
  })

  // The screen keeps its heading (and so its document title) while it loads or fails.
  const loadingHeader = <PageHeader title={t('evidenceTitle')} subtitle={t('evidenceSubtitle')} />
  if (sources.isLoading) return <>{loadingHeader}<Spinner /></>
  if (sources.error) return <>{loadingHeader}<ErrorBanner error={sources.error} onRetry={sources.refetch} /></>

  const rows = sources.data ?? []

  return (
    <>
      <PageHeader title={t('evidenceTitle')} subtitle={t('evidenceSubtitle')}
                  actions={<button type="button" className="btn-primary"
                                   onClick={() => setUploading(true)}>{t('upload')}</button>} />

      {limits.data ? (
        <div className="mb-4">
          <Note tone="muted">
            Limits: {Math.round(limits.data.maxDocumentBytes / 1024 / 1024)} MB per document,
            {' '}{Math.round(limits.data.maxRecordingBytes / 1024 / 1024 / 1024)} GB per
            recording. {limits.data.notes.join(' ')}
          </Note>
        </div>
      ) : null}

      {impact.data?.length ? (
        <div className="mb-4">
          <Note tone="warning">
            {impact.data.length} change impact report(s): a source revision marked
            {' '}{impact.data[0].summary.items ?? 0} item(s) and
            {' '}{impact.data[0].summary.tests ?? 0} test(s) as potentially stale.
            Approved history stays available; current artifacts need review.
          </Note>
        </div>
      ) : null}

      {rows.length === 0 ? (
        <EmptyState title="No evidence yet"
                    hint="Upload briefs, meeting notes, spreadsheets, designs or recordings. Originals stay on company infrastructure."
                    action={<button type="button" className="btn-primary"
                                    onClick={() => setUploading(true)}>{t('upload')}</button>} />
      ) : (
        <Section title="Sources" description="Current version of each source document">
          <Table
            rows={rows}
            rowKey={(row) => row.id}
            onRowClick={(row) => !row.accessRestricted && setSelected(row.id)}
            columns={[
              { key: 'title', header: 'Source',
                render: (row) => (
                  <div>
                    <p className="font-medium text-ink-900">{row.title}</p>
                    <p className="text-xs text-ink-500">
                      {row.filename ?? '—'} · v{row.currentVersion}
                    </p>
                  </div>
                ) },
              { key: 'kind', header: 'Kind', render: (row) => row.kind.replace('_', ' ') },
              { key: 'classification', header: t('classification'),
                render: (row) => (
                  <Badge tone={row.classification === 'restricted' ? 'critical'
                    : row.classification === 'confidential' ? 'warning' : 'good'}>
                    {row.classification}
                  </Badge>
                ) },
              { key: 'authority', header: t('authority'), render: (row) => row.authority },
              { key: 'status', header: t('extraction'),
                render: (row) => (
                  <div className="space-y-1">
                    <Badge tone={STATUS_TONE[row.status] ?? 'neutral'}>{row.status}</Badge>
                    {row.warnings.map((warning) => (
                      <p key={warning.code} className="text-xs text-amber-700">
                        {warning.message}
                      </p>
                    ))}
                  </div>
                ) },
              { key: 'chunks', header: 'Excerpts', align: 'right',
                render: (row) => row.accessRestricted ? '—' : row.chunkCount },
              { key: 'created', header: 'Uploaded',
                render: (row) => formatDateTime(row.createdAt) },
            ]} />
        </Section>
      )}

      {selected ? (
        <SourceDetail projectId={projectId} documentId={selected}
                      onClose={() => setSelected(null)} />
      ) : null}

      <UploadModal
        open={uploading}
        onClose={() => setUploading(false)}
        onUploaded={() => {
          void queryClient.invalidateQueries({ queryKey: ['sources', projectId] })
          void queryClient.invalidateQueries({ queryKey: ['impact', projectId] })
          setUploading(false)
        }}
        projectId={projectId}
        existing={rows}
      />
    </>
  )
}

function SourceDetail({ projectId, documentId, onClose }: {
  projectId: string; documentId: string; onClose: () => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [transcriptText, setTranscriptText] = useState('')

  const content = useQuery({
    queryKey: ['source-content', projectId, documentId],
    queryFn: () => api<{
      accessRestricted: boolean; message?: string; versionId: string
      total: number; chunks: SourceChunk[]
    }>(`/projects/${projectId}/sources/${documentId}/content`, { query: { limit: 400 } }),
  })
  const versions = useQuery({
    queryKey: ['source-versions', projectId, documentId],
    queryFn: () => api<Record<string, unknown>[]>(
      `/projects/${projectId}/sources/${documentId}/versions`),
  })
  const transcript = useQuery({
    queryKey: ['transcript', projectId, documentId],
    queryFn: () => api<TranscriptSegment[]>(
      `/projects/${projectId}/sources/${documentId}/transcript`),
  })

  const attach = useMutation({
    mutationFn: (text: string) => api(
      `/projects/${projectId}/sources/versions/${content.data?.versionId}/transcript`,
      { method: 'POST', body: { text } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['transcript', projectId, documentId] })
      void queryClient.invalidateQueries({ queryKey: ['source-content', projectId, documentId] })
      setTranscriptText('')
    },
  })
  const correct = useMutation({
    mutationFn: ({ id, text, speaker }: { id: string; text?: string; speaker?: string }) =>
      api(`/projects/${projectId}/sources/segments/${id}`, {
        method: 'PATCH', body: { text, speaker },
      }),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['transcript', projectId, documentId] }),
  })

  return (
    <Modal open wide title="Source viewer" onClose={onClose}>
      {content.isLoading ? <Spinner /> : null}
      {content.data?.accessRestricted ? (
        <Note tone="warning">{content.data.message ?? t('restrictedSourceHelp')}</Note>
      ) : null}

      {content.data && !content.data.accessRestricted ? (
        <div className="space-y-4">
          <section>
            <h3 className="mb-2 text-sm font-semibold text-ink-900">
              Extracted excerpts ({content.data.total})
            </h3>
            <div className="max-h-80 space-y-2 overflow-y-auto rounded-lg border
                            border-ink-200 p-3">
              {content.data.chunks.map((chunk) => (
                <article key={chunk.id} className="border-b border-ink-100 pb-2 last:border-0">
                  <p className="text-xs text-ink-500">
                    <code className="rounded bg-ink-100 px-1">
                      {chunk.locatorKind}:{chunk.locatorValue}
                    </code>
                    {chunk.speaker ? ` · ${chunk.speaker}` : ''}
                    {chunk.lowConfidence ? ' · low confidence' : ''}
                  </p>
                  <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink-800">{chunk.text}</p>
                </article>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-ink-900">{t('versions')}</h3>
            <div className="space-y-1 text-xs">
              {(versions.data ?? []).map((version) => (
                <div key={String(version.id)}
                     className="flex flex-wrap items-center gap-2 rounded border
                                border-ink-200 px-2 py-1">
                  <Badge tone="muted">v{String(version.version)}</Badge>
                  <span>{String(version.filename)}</span>
                  <span className="text-ink-500">{String(version.status)}</span>
                  <span className="text-ink-500">
                    {String(version.extractor)} {String(version.extractorVersion ?? '')}
                  </span>
                  {version.failureReason ? (
                    <span className="text-red-700">{String(version.failureReason)}</span>
                  ) : null}
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-ink-900">{t('transcript')}</h3>
            {transcript.data?.length ? (
              <div className="max-h-64 space-y-1 overflow-y-auto rounded-lg border
                              border-ink-200 p-3">
                {transcript.data.map((segment) => (
                  <div key={segment.id} className="flex flex-wrap items-start gap-2 text-sm sm:flex-nowrap">
                    <code className="shrink-0 text-xs text-ink-500">
                      {formatMs(segment.startMs)}
                    </code>
                    <input
                      className="w-32 shrink-0 rounded border border-ink-400 px-1 text-base sm:text-xs"
                      defaultValue={segment.speaker ?? ''}
                      aria-label={`Speaker at ${formatMs(segment.startMs)}`}
                      placeholder="speaker"
                      onBlur={(event) => event.target.value !== (segment.speaker ?? '')
                        && correct.mutate({ id: segment.id, speaker: event.target.value })}
                    />
                    <input
                      className="min-w-0 flex-1 basis-full rounded border border-ink-400 px-1 text-base sm:basis-auto sm:text-sm"
                      defaultValue={segment.text}
                      aria-label={`Transcript text at ${formatMs(segment.startMs)}`}
                      onBlur={(event) => event.target.value !== segment.text
                        && correct.mutate({ id: segment.id, text: event.target.value })}
                    />
                    {segment.corrected ? <Badge tone="good">corrected</Badge> : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                <Note tone="muted">
                  No transcript yet. Speaker labels are suggestions and never imply a
                  verified identity.
                </Note>
                <textarea className="input h-28 font-mono text-base sm:text-xs"
                          aria-label="Transcript to attach"
                          placeholder="[00:12] Client: we need the invoice list to load quickly"
                          value={transcriptText}
                          onChange={(event) => setTranscriptText(event.target.value)} />
                <button type="button" className="btn-secondary"
                        disabled={!transcriptText || attach.isPending}
                        onClick={() => attach.mutate(transcriptText)}>
                  Attach transcript
                </button>
                {attach.error ? <ErrorBanner error={attach.error} /> : null}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </Modal>
  )
}

function formatMs(ms: number) {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function UploadModal({ open, onClose, onUploaded, projectId, existing }: {
  open: boolean
  onClose: () => void
  onUploaded: () => void
  projectId: string
  existing: SourceView[]
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState('brief')
  const [authority, setAuthority] = useState('working')
  const [classification, setClassification] = useState('')
  const [documentId, setDocumentId] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit() {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      await uploadSource(projectId, file, {
        title: title || file.name,
        kind,
        authority,
        classification: classification || undefined,
      }, documentId || undefined)
      onUploaded()
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} title="Upload evidence" onClose={onClose}
           footer={
             <>
               <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
               <button type="button" className="btn-primary" disabled={busy}
                       onClick={submit}>{busy ? 'Uploading…' : 'Upload'}</button>
             </>
           }>
      <div className="space-y-3">
        <Field label="File">
          <input ref={fileRef} type="file" className="input" />
        </Field>
        <Field label="Title"><input className="input" value={title}
          onChange={(event) => setTitle(event.target.value)} /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Kind">
            <select className="input" value={kind}
                    onChange={(event) => setKind(event.target.value)}>
              {KINDS.map((value) => (
                <option key={value} value={value}>{value.replace('_', ' ')}</option>
              ))}
            </select>
          </Field>
          <Field label="Authority" hint="Used when evidence conflicts">
            <select className="input" value={authority}
                    onChange={(event) => setAuthority(event.target.value)}>
              <option value="contractual">Contractual</option>
              <option value="confirmed">Confirmed</option>
              <option value="working">Working</option>
              <option value="indicative">Indicative</option>
            </select>
          </Field>
          <Field label="Classification" hint="Defaults to the project setting">
            <select className="input" value={classification}
                    onChange={(event) => setClassification(event.target.value)}>
              <option value="">Project default</option>
              <option value="restricted">Restricted</option>
              <option value="confidential">Confidential</option>
              <option value="shareable">Shareable</option>
            </select>
          </Field>
        </div>
        <Field label="New version of" hint="Re-imports create a version; history is never overwritten">
          <select className="input" value={documentId}
                  onChange={(event) => setDocumentId(event.target.value)}>
            <option value="">New source</option>
            {existing.map((source) => (
              <option key={source.id} value={source.id}>{source.title}</option>
            ))}
          </select>
        </Field>
        {error ? <ErrorBanner error={error} /> : null}
      </div>
    </Modal>
  )
}
