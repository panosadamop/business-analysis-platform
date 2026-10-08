/** Screen 11 — report builder: dataset, fields, filters, preview and exports. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api, download } from '../lib/api'
import { useI18n } from '../i18n'
import {
  DEFAULT_CHART_SETTINGS, ReportChart, ReportChartControls,
} from '../components/report-chart'
import type { ChartSettings } from '../components/report-chart'
import {
  Badge, ErrorBanner, Field, Note, PageHeader, Section, Spinner, Table, formatDateTime,
} from '../components/ui'
import type { ReportPreview } from '../types'

interface DatasetTemplate {
  dataset: string
  name: string
  columns: { key: string; label: string; type: string; clientSafe: boolean }[]
  allowedColumns: { key: string; label: string; type: string }[]
}

const FORMATS = [
  { value: 'xlsx', label: 'Excel .xlsx' },
  { value: 'xls', label: 'Legacy .xls' },
  { value: 'json', label: 'Versioned JSON' },
  { value: 'markdown', label: 'Markdown specifications' },
  { value: 'gherkin', label: 'Gherkin .feature bundle' },
  { value: 'zip', label: 'ZIP bundle' },
]

export function ReportsPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const [dataset, setDataset] = useState('backlog')
  const [fields, setFields] = useState<string[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [format, setFormat] = useState('xlsx')
  const [preview, setPreview] = useState<ReportPreview | null>(null)
  const [chart, setChart] = useState<ChartSettings>(DEFAULT_CHART_SETTINGS)
  const [saving, setSaving] = useState(false)

  const datasets = useQuery({
    queryKey: ['report-datasets', projectId],
    queryFn: () => api<DatasetTemplate[]>(`/projects/${projectId}/reports/datasets`),
  })
  const exports = useQuery({
    queryKey: ['exports', projectId],
    queryFn: () => api<{ id: string; format: string; status: string; filename?: string | null
                         rowCounts: Record<string, number>; warnings: string[]
                         createdAt: string }[]>(`/projects/${projectId}/exports`),
  })

  const definitions = useQuery({
    queryKey: ['report-definitions', projectId],
    queryFn: () => api<{ id: string; name: string; dataset: string; fields: string[]
                         filters: Record<string, string>; chartType?: string | null }[]>(
      `/projects/${projectId}/reports/definitions`),
  })

  const runPreview = useMutation({
    mutationFn: () => api<ReportPreview>(`/projects/${projectId}/reports/preview`, {
      method: 'POST', body: { dataset, fields, filters, limit: 500 },
    }),
    onSuccess: (result) => {
      setPreview(result)
      // Offer a sensible first chart: group by the first text column, measure
      // the first numeric one.
      setChart((current) => {
        if (current.groupBy) return current
        const group = result.columns.find((column) => column.type === 'string')
        const measure = result.columns.find(
          (column) => column.type === 'number' || column.type === 'money')
        return { ...current, groupBy: group?.key ?? '', measure: measure?.key ?? '' }
      })
    },
  })

  const saveDefinition = useMutation({
    mutationFn: (name: string) =>
      api(`/projects/${projectId}/reports/definitions`, {
        method: 'POST',
        body: { name, dataset, fields, filters, chartType: chart.chartType,
                sharedWithProject: true },
      }),
    onSuccess: () => {
      void definitions.refetch()
      setSaving(false)
    },
  })

  const runExport = useMutation({
    mutationFn: () => api<{ exportJobId: string; filename: string; warnings: string[] }>(
      `/projects/${projectId}/exports`, {
        method: 'POST',
        body: { dataset: format === 'markdown' || format === 'gherkin' ? null : dataset,
                format, filters, fields },
      }),
    onSuccess: () => exports.refetch(),
  })

  const current = datasets.data?.find((item) => item.dataset === dataset)
  const hiddenColumns = (current?.columns.length ?? 0) - (current?.allowedColumns.length ?? 0)

  return (
    <>
      <PageHeader title={t('reportsTitle')} subtitle={t('reportsSubtitle')} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Section title="Definition">
          <div className="space-y-3">
            <Field label={t('dataset')}>
              <select className="input" value={dataset}
                      onChange={(event) => { setDataset(event.target.value); setFields([]) }}>
                {(datasets.data ?? []).map((item) => (
                  <option key={item.dataset} value={item.dataset}>{item.name}</option>
                ))}
              </select>
            </Field>

            <fieldset>
              <legend className="label mb-1">{t('fields')}</legend>
              <div className="max-h-56 space-y-1 overflow-y-auto rounded border
                              border-ink-200 p-2">
                {(current?.allowedColumns ?? []).map((column) => (
                  <label key={column.key} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={fields.includes(column.key)}
                           onChange={(event) => setFields(event.target.checked
                             ? [...fields, column.key]
                             : fields.filter((key) => key !== column.key))} />
                    {column.label}
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-ink-500">
                No selection means every field you are permitted to read.
                {hiddenColumns > 0
                  ? ` ${hiddenColumns} column(s) are hidden by your permissions.`
                  : ''}
              </p>
            </fieldset>

            <fieldset aria-describedby="report-filters-hint">
              <legend className="label mb-1">Filters</legend>
              <div className="space-y-2">
                {['approvalState', 'executionStatus', 'type', 'severity', 'status'].map((key) => (
                  <div key={key} className="flex items-center gap-2">
                    <label htmlFor={`report-filter-${key}`}
                           className="w-32 text-xs text-ink-500">{key}</label>
                    <input id={`report-filter-${key}`} className="input"
                           value={filters[key] ?? ''}
                           onChange={(event) => setFilters({
                             ...filters, [key]: event.target.value })} />
                  </div>
                ))}
              </div>
              <p id="report-filters-hint" className="mt-1 text-xs text-ink-500">
                Only allowlisted filters are accepted
              </p>
            </fieldset>

            <div className="flex gap-2">
              <button type="button" className="btn-primary flex-1"
                      disabled={runPreview.isPending}
                      onClick={() => runPreview.mutate()}>{t('preview')}</button>
              <button type="button" className="btn-secondary"
                      onClick={() => setSaving(true)}>Save</button>
            </div>
            {saving ? (
              <form className="flex gap-2"
                    onSubmit={(event) => {
                      event.preventDefault()
                      const name = new FormData(event.currentTarget).get('name')
                      if (name) saveDefinition.mutate(String(name))
                    }}>
                <input name="name" className="input" required aria-label="Report name"
                       placeholder="Name this report" />
                <button type="submit" className="btn-secondary"
                        disabled={saveDefinition.isPending}>Save</button>
              </form>
            ) : null}
            {saveDefinition.error ? <ErrorBanner error={saveDefinition.error} /> : null}
            {definitions.data?.length ? (
              <Field label="Saved reports">
                <select className="input"
                        onChange={(event) => {
                          const found = definitions.data?.find(
                            (row) => row.id === event.target.value)
                          if (!found) return
                          setDataset(found.dataset)
                          setFields(found.fields)
                          setFilters(found.filters ?? {})
                          setChart((current) => ({
                            ...current,
                            chartType: (found.chartType as ChartSettings['chartType'])
                              ?? 'table',
                          }))
                        }}>
                  <option value="">Load a saved report…</option>
                  {definitions.data.map((row) => (
                    <option key={row.id} value={row.id}>{row.name}</option>
                  ))}
                </select>
              </Field>
            ) : null}

            <Field label="Export format">
              <select className="input" value={format}
                      onChange={(event) => setFormat(event.target.value)}>
                {FORMATS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </Field>
            <button type="button" className="btn-secondary w-full"
                    disabled={runExport.isPending}
                    onClick={() => runExport.mutate()}>
              {runExport.isPending ? t('loading') : t('export')}
            </button>
            {format === 'xls' ? (
              <Note tone="warning">
                Legacy .xls enforces 65,536 rows and 256 columns per sheet. Output splits
                across sheets with a manifest rather than truncating.
              </Note>
            ) : null}
            {runPreview.error ? <ErrorBanner error={runPreview.error} /> : null}
            {runExport.error ? <ErrorBanner error={runExport.error} /> : null}
          </div>
        </Section>

        <div className="space-y-4">
          {preview ? (
            <Section title={`${t('preview')} — ${preview.dataset}`}
                     description={`${preview.totalRows} rows · snapshot ${preview.snapshotId}`}>
              {preview.warnings.length ? (
                <ul className="mb-2 space-y-1">
                  {preview.warnings.map((warning) => (
                    <li key={warning} className="text-xs text-amber-700">· {warning}</li>
                  ))}
                </ul>
              ) : null}
              {Object.keys(preview.totals).length ? (
                <div className="mb-3 flex flex-wrap gap-2">
                  {Object.entries(preview.totals).map(([key, value]) => (
                    <Badge key={key} tone="muted">
                      {key}: {typeof value === 'object'
                        ? JSON.stringify(value) : String(value)}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <div className="mb-4 rounded-lg border border-ink-200 p-3">
                <ReportChartControls columns={preview.columns} settings={chart}
                                     onChange={setChart} />
              </div>

              {chart.chartType !== 'table' ? (
                <div className="mb-4">
                  <ReportChart preview={preview} settings={chart} />
                </div>
              ) : null}

              <div className="overflow-x-auto">
                <table className="min-w-full">
                  <thead>
                    <tr className="border-b border-ink-200">
                      {preview.columns.map((column) => (
                        <th key={column.key} className="th">{column.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row, index) => (
                      <tr key={index} className="border-b border-ink-100 last:border-0">
                        {preview.columns.map((column) => (
                          <td key={column.key} className="td">
                            {formatCell(row[column.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          ) : (
            <Section title={t('preview')}>
              {runPreview.isPending ? <Spinner /> : (
                <p className="py-8 text-center text-sm text-ink-500">
                  Choose a dataset and preview it. Column level restrictions are applied on
                  the server, including fields derived from hidden costs.
                </p>
              )}
            </Section>
          )}

          <Section title="Exports"
                   description="Each export records its row counts, warnings, schema version and the permissions applied.">
            <Table
              rows={exports.data ?? []}
              rowKey={(row) => row.id}
              empty="No exports yet"
              columns={[
                { key: 'created', header: 'Created',
                  render: (row) => formatDateTime(row.createdAt) },
                { key: 'format', header: 'Format', render: (row) => row.format },
                { key: 'status', header: 'Status',
                  render: (row) => <Badge tone={row.status === 'succeeded' ? 'good' : 'info'}>
                    {row.status}</Badge> },
                { key: 'rows', header: 'Rows',
                  render: (row) => Object.entries(row.rowCounts)
                    .map(([name, count]) => `${name}: ${count}`).join(' · ') || '—' },
                { key: 'warnings', header: 'Warnings',
                  render: (row) => row.warnings.length
                    ? <span className="text-xs text-amber-700">
                        {row.warnings.join(' ')}
                      </span>
                    : '—' },
                { key: 'download', header: '', align: 'right',
                  render: (row) => row.filename ? (
                    <button type="button" className="btn-secondary text-xs"
                            onClick={() => download(
                              `/projects/${projectId}/exports/${row.id}/download`,
                              row.filename!)}>
                      Download
                    </button>
                  ) : null },
              ]} />
          </Section>
        </div>
      </div>
    </>
  )
}

function formatCell(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
