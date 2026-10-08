/** Screen 10 — project dashboards: effort, cost, flow, quality and scope. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import { ServerChart, StatTile } from '../components/charts'
import { ErrorBanner, Field, Note, PageHeader, Spinner } from '../components/ui'
import type { ChartResponse, Iteration } from '../types'

export function DashboardsPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const [iterationId, setIterationId] = useState('')
  const [unit, setUnit] = useState<'story_points' | 'person_hours'>('story_points')
  const [baselineId, setBaselineId] = useState('')

  const iterations = useQuery({
    queryKey: ['iterations', projectId],
    queryFn: () => api<Iteration[]>(`/projects/${projectId}/iterations`),
  })
  const baselines = useQuery({
    queryKey: ['baselines', projectId],
    queryFn: () => api<{ id: string; name: string }[]>(`/projects/${projectId}/baselines`),
  })

  const chart = (name: string, query: Record<string, string> = {}) =>
    useQuery({
      queryKey: ['chart', projectId, name, query],
      queryFn: () => api<ChartResponse>(`/projects/${projectId}/charts/${name}`, { query }),
      retry: false,
    })

  const plannedActual = chart('planned_vs_actual', baselineId ? { baselineId } : {})
  const cost = chart('cost')
  const burndown = chart('burndown', iterationId ? { iterationId, unit } : {})
  const velocity = chart('velocity')
  const flow = chart('cumulative_flow')
  const cycle = chart('cycle_time')
  const quality = chart('quality_scope')
  const milestones = chart('milestones')

  const activeIteration = iterations.data?.find((item) => item.state === 'active')
  const effectiveIteration = iterationId || activeIteration?.id || ''

  const qualityPoints = quality.data?.series[0]?.points ?? []
  const valueOf = (category: string) =>
    Number(qualityPoints.find((point) => point.category === category)?.value ?? 0)

  return (
    <>
      <PageHeader title={t('dashboardsTitle')} subtitle={t('dashboardsSubtitle')} />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-56">
          <Field label="Sprint">
            <select className="input" value={effectiveIteration}
                    onChange={(event) => setIterationId(event.target.value)}>
              <option value="">Select a sprint…</option>
              {(iterations.data ?? []).map((iteration) => (
                <option key={iteration.id} value={iteration.id}>{iteration.name}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="w-48">
          <Field label="Burndown unit">
            <select className="input" value={unit}
                    onChange={(event) => setUnit(event.target.value as typeof unit)}>
              <option value="story_points">Story points</option>
              <option value="person_hours">Person hours</option>
            </select>
          </Field>
        </div>
        <div className="w-56">
          <Field label="Baseline">
            <select className="input" value={baselineId}
                    onChange={(event) => setBaselineId(event.target.value)}>
              <option value="">No baseline</option>
              {(baselines.data ?? []).map((baseline) => (
                <option key={baseline.id} value={baseline.id}>{baseline.name}</option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      {quality.data ? (
        <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <StatTile label="Approved items"
                    value={`${valueOf('approved')}/${valueOf('items')}`} />
          <StatTile label="Stories with a test"
                    value={`${valueOf('stories tested')}/${valueOf('stories')}`}
                    tone={valueOf('stories tested') < valueOf('stories') ? 'warning' : 'good'} />
          <StatTile label="Open questions" value={valueOf('open questions')}
                    tone={valueOf('critical questions') ? 'critical' : 'neutral'}
                    hint={`${valueOf('critical questions')} critical`} />
          <StatTile label="Open findings" value={valueOf('open findings')}
                    tone={valueOf('open findings') ? 'warning' : 'good'} />
          <StatTile label="Blocked items" value={valueOf('blocked')}
                    tone={valueOf('blocked') ? 'critical' : 'good'}
                    hint={valueOf('started')
                      ? `of ${valueOf('started')} started on the board`
                      : 'Nothing started on the board yet'} />
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartSlot query={plannedActual} kind="bar" />
        <ChartSlot query={cost} kind="bar" deniedMessage="Cost charts need the cost.read permission." />
        <ChartSlot query={burndown} kind="line" />
        <ChartSlot query={velocity} kind="bar" />
        <ChartSlot query={flow} kind="stacked" />
        <ChartSlot query={cycle} kind="bar" />
        <ChartSlot query={quality} kind="bar" />
        <ChartSlot query={milestones} kind="bar" />
      </div>

      <div className="mt-4">
        <Note tone="muted">
          Completion percentage uses an explicitly selected weighting policy. A "done"
          status alone does not imply that tests passed, and forecasts disclose their data
          sufficiency.
        </Note>
      </div>
    </>
  )
}

function ChartSlot({ query, kind, deniedMessage }: {
  query: { isLoading: boolean; error: unknown; data?: ChartResponse }
  kind: 'bar' | 'line' | 'area' | 'stacked'
  deniedMessage?: string
}) {
  if (query.isLoading) return <div className="card card-pad"><Spinner /></div>
  if (query.error) {
    const status = (query.error as { status?: number }).status
    if (status === 403 && deniedMessage) {
      return <div className="card card-pad"><Note tone="muted">{deniedMessage}</Note></div>
    }
    return <div className="card card-pad"><ErrorBanner error={query.error} /></div>
  }
  if (!query.data) return null
  return <ServerChart data={query.data} kind={kind} />
}
