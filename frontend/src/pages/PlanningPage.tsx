/** Screen 8 — planning workspace: sprints, Kanban, capacity, milestones, time. */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import { KanbanBoard } from '../components/KanbanBoard'
import {
  AddAllocationModal, AddMilestoneModal, AddSprintModal,
} from '../components/entry-forms'
import {
  Badge, ErrorBanner, Field, Note, PageHeader, Section, Spinner, Table, Tabs,
} from '../components/ui'
import type { BoardState, CapacityRow, Iteration, Member } from '../types'

export function PlanningPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('board')
  const [adding, setAdding] = useState<'sprint' | 'milestone' | 'allocation' | null>(null)

  const iterations = useQuery({
    queryKey: ['iterations', projectId],
    queryFn: () => api<Iteration[]>(`/projects/${projectId}/iterations`),
  })
  const board = useQuery({
    queryKey: ['board-state', projectId],
    queryFn: () => api<BoardState>(`/projects/${projectId}/board/state`),
  })
  const capacity = useQuery({
    queryKey: ['capacity', projectId],
    queryFn: () => api<CapacityRow[]>(`/projects/${projectId}/capacity`),
  })
  const milestones = useQuery({
    queryKey: ['milestones', projectId],
    queryFn: () => api<{ id: string; name: string; dueDate: string; baselineDate?: string | null
                         forecastDate?: string | null; status: string }[]>(
      `/projects/${projectId}/milestones`),
  })
  const worklogs = useQuery({
    queryKey: ['worklogs', projectId],
    queryFn: () => api<{ id: string; workDate: string; hours: number; role?: string | null
                         approved: boolean; note?: string | null; itemId?: string | null }[]>(
      `/projects/${projectId}/worklogs`),
  })

  const members = useQuery({
    queryKey: ['members', projectId],
    queryFn: () => api<Member[]>(`/projects/${projectId}/members`),
  })

  const addEntry = useMutation({
    mutationFn: ({ path, body }: { path: string; body: Record<string, unknown> }) =>
      api(`/projects/${projectId}/${path}`, { method: 'POST', body }),
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: [variables.path, projectId] })
      void queryClient.invalidateQueries({ queryKey: ['capacity', projectId] })
      setAdding(null)
    },
  })

  const logTime = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/worklogs`, { method: 'POST', body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worklogs', projectId] }),
  })
  const approveTime = useMutation({
    mutationFn: (id: string) =>
      api(`/projects/${projectId}/worklogs/${id}/approve`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worklogs', projectId] }),
  })

  return (
    <>
      <PageHeader title={t('planningTitle')} subtitle={t('planningSubtitle')}
                  actions={
                    <>
                      <button type="button" className="btn-secondary"
                              onClick={() => setAdding('sprint')}>Add sprint</button>
                      <button type="button" className="btn-secondary"
                              onClick={() => setAdding('milestone')}>Add milestone</button>
                      <button type="button" className="btn-secondary"
                              onClick={() => setAdding('allocation')}>
                        Allocate a person
                      </button>
                    </>
                  } />

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: 'board', label: t('board') },
        { key: 'sprints', label: t('sprints'), count: iterations.data?.length },
        { key: 'capacity', label: t('capacity') },
        { key: 'milestones', label: t('milestones'), count: milestones.data?.length },
        { key: 'time', label: t('worklogs'), count: worklogs.data?.length },
      ]} />

      {tab === 'board' ? (
        board.isLoading ? <Spinner /> : (
          <Section title={t('board')} description={board.data?.note}>
            {board.data ? <KanbanBoard projectId={projectId} board={board.data} /> : null}
          </Section>
        )
      ) : null}

      {tab === 'sprints' ? (
        <Section title={t('sprints')} description="Sprint goals, capacity and state"
                 actions={<button type="button" className="btn-secondary text-xs"
                                  onClick={() => setAdding('sprint')}>Add sprint</button>}>
          <Table
            rows={iterations.data ?? []}
            rowKey={(row) => row.id}
            empty="No iterations configured"
            columns={[
              { key: 'name', header: 'Sprint', render: (row) => row.name },
              { key: 'goal', header: 'Goal', render: (row) => row.goal ?? '—' },
              { key: 'dates', header: 'Dates',
                render: (row) => `${row.startDate} → ${row.endDate}` },
              { key: 'state', header: 'State',
                render: (row) => <Badge tone={row.state === 'active' ? 'good' : 'muted'}>
                  {row.state}</Badge> },
              { key: 'capacity', header: 'Capacity', align: 'right',
                render: (row) => `${row.capacityHours} h` },
            ]} />
        </Section>
      ) : null}

      {tab === 'capacity' ? (
        <Section title={t('capacity')}
                 description="Scheduled hours less leave, multiplied by allocation and the configured focus factor."
                 actions={<button type="button" className="btn-secondary text-xs"
                                  onClick={() => setAdding('allocation')}>
                   Allocate a person
                 </button>}>
          <Table
            rows={capacity.data ?? []}
            rowKey={(row) => row.userId}
            empty="No members with capacity in this period"
            columns={[
              { key: 'name', header: 'Person', render: (row) => row.displayName },
              { key: 'role', header: 'Role', render: (row) => row.role ?? '—' },
              { key: 'scheduled', header: 'Scheduled', align: 'right',
                render: (row) => `${row.scheduledHours} h` },
              { key: 'leave', header: 'Leave', align: 'right',
                render: (row) => `${row.leaveHours} h` },
              { key: 'allocation', header: 'Allocation', align: 'right',
                render: (row) => `${row.allocationPercent}%` },
              { key: 'focus', header: 'Focus', align: 'right',
                render: (row) => row.focusFactor },
              { key: 'available', header: t('available'), align: 'right',
                render: (row) => <strong>{row.availableHours} h</strong> },
            ]} />
        </Section>
      ) : null}

      {tab === 'milestones' ? (
        <Section title={t('milestones')}
                 description="Baseline date against the current forecast"
                 actions={<button type="button" className="btn-secondary text-xs"
                                  onClick={() => setAdding('milestone')}>
                   Add milestone
                 </button>}>
          <Table
            rows={milestones.data ?? []}
            rowKey={(row) => row.id}
            empty="No milestones recorded"
            columns={[
              { key: 'name', header: 'Milestone', render: (row) => row.name },
              { key: 'baseline', header: 'Baseline',
                render: (row) => row.baselineDate ?? row.dueDate },
              { key: 'forecast', header: 'Forecast',
                render: (row) => row.forecastDate ?? row.dueDate },
              { key: 'status', header: 'Status', render: (row) => row.status },
            ]} />
        </Section>
      ) : null}

      {tab === 'time' ? (
        <div className="space-y-4">
          <Section title="Record time">
            <form className="grid grid-cols-1 gap-3 sm:grid-cols-4"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const form = new FormData(event.currentTarget)
                    logTime.mutate({
                      workDate: form.get('workDate'),
                      hours: Number(form.get('hours')),
                      role: form.get('role') || null,
                      note: form.get('note') || null,
                    })
                    event.currentTarget.reset()
                  }}>
              <Field label="Date">
                <input name="workDate" type="date" className="input" required
                       defaultValue={new Date().toISOString().slice(0, 10)} />
              </Field>
              <Field label="Hours">
                <input name="hours" type="number" step="0.25" min="0.25" className="input"
                       required />
              </Field>
              <Field label="Role"><input name="role" className="input" /></Field>
              <div className="flex items-end">
                <button type="submit" className="btn-primary w-full">Record</button>
              </div>
              <div className="sm:col-span-4">
                <Field label="Note"><input name="note" className="input" /></Field>
              </div>
            </form>
            {logTime.error ? <ErrorBanner error={logTime.error} /> : null}
            <div className="mt-3">
              <Note tone="muted">
                Only approved entries count towards actual effort and actual cost.
              </Note>
            </div>
          </Section>

          <Section title={t('worklogs')}>
            <Table
              rows={worklogs.data ?? []}
              rowKey={(row) => row.id}
              empty="No time recorded"
              columns={[
                { key: 'date', header: 'Date', render: (row) => row.workDate },
                { key: 'hours', header: 'Hours', align: 'right', render: (row) => row.hours },
                { key: 'role', header: 'Role', render: (row) => row.role ?? '—' },
                { key: 'note', header: 'Note', render: (row) => row.note ?? '—' },
                { key: 'approved', header: 'Approved',
                  render: (row) => row.approved
                    ? <Badge tone="good">approved</Badge>
                    : <button type="button" className="btn-secondary text-xs"
                              onClick={() => approveTime.mutate(row.id)}>Approve</button> },
              ]} />
          </Section>
        </div>
      ) : null}
      <AddSprintModal open={adding === 'sprint'} onClose={() => setAdding(null)}
                      onCreate={(body) => addEntry.mutate({ path: 'iterations', body })}
                      busy={addEntry.isPending} error={addEntry.error} />
      <AddMilestoneModal open={adding === 'milestone'} onClose={() => setAdding(null)}
                         onCreate={(body) => addEntry.mutate({ path: 'milestones', body })}
                         busy={addEntry.isPending} error={addEntry.error} />
      <AddAllocationModal open={adding === 'allocation'} onClose={() => setAdding(null)}
                          onCreate={(body) =>
                            addEntry.mutate({ path: 'allocations', body })}
                          busy={addEntry.isPending} error={addEntry.error}
                          people={(members.data ?? []).map((member) => ({
                            userId: member.userId, displayName: member.displayName,
                          }))} />
    </>
  )
}
