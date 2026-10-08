/** Screen 2 — project setup: members, method, language, calendar, rates, AI policy. */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useI18n } from '../i18n'
import { DEFAULT_ANALYSTS, AnalystPicker } from '../components/analysts'
import { AddRateCardModal } from '../components/entry-forms'
import {
  Badge, ErrorBanner, Field, Modal, Note, PageHeader, Section, Spinner, Table, Tabs,
} from '../components/ui'
import type { Member, Project } from '../types'

const ROLES = [
  'project_admin', 'lead_analyst', 'business_analyst', 'technical_analyst',
  'qa_analyst', 'ux_analyst', 'data_analyst', 'delivery_manager', 'contributor', 'client_reviewer', 'internal_viewer',
]

export function ProjectSetupPage() {
  const { projectId = '' } = useParams()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('general')
  const [inviting, setInviting] = useState(false)
  const [addingRateCard, setAddingRateCard] = useState(false)

  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api<Project>(`/projects/${projectId}`),
  })
  const members = useQuery({
    queryKey: ['members', projectId],
    queryFn: () => api<Member[]>(`/projects/${projectId}/members`),
  })
  const policy = useQuery({
    queryKey: ['policy', projectId],
    queryFn: () => api<{
      policy: Record<string, unknown>
      effective: Record<string, unknown>[]
      explanation: string[]
    }>(`/projects/${projectId}/policy`),
  })
  const rateCards = useQuery({
    queryKey: ['rate-cards', projectId],
    queryFn: () => api<{ id: string; name: string; currency: string; effectiveFrom: string;
                         rates: Record<string, string>; contingencyPercent: number }[]>(
      `/projects/${projectId}/rate-cards`),
    retry: false,
  })

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}`, { method: 'PATCH', body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['project', projectId] }),
  })
  const addRateCard = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/rate-cards`, { method: 'POST', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['rate-cards', projectId] })
      setAddingRateCard(false)
    },
  })
  const invite = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/projects/${projectId}/members`, { method: 'POST', body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['members', projectId] })
      setInviting(false)
    },
  })

  const [draft, setDraft] = useState<Project | null>(null)
  useEffect(() => { if (project.data) setDraft(project.data) }, [project.data])

  // The screen keeps its heading (and so its document title) while it loads or fails.
  // The error is checked first: a failed load never fills the draft.
  const loadingHeader = <PageHeader title={t('navSetup')} />
  if (project.error) return <>{loadingHeader}<ErrorBanner error={project.error} /></>
  if (project.isLoading || !draft) return <>{loadingHeader}<Spinner /></>

  return (
    <>
      <PageHeader title={t('navSetup')} subtitle={`${draft.key} — ${draft.name}`}
                  actions={
                    <button type="button" className="btn-primary"
                            disabled={update.isPending}
                            onClick={() => update.mutate({
                              name: draft.name,
                              clientName: draft.clientName,
                              description: draft.description,
                              outputLanguage: draft.outputLanguage,
                              deliveryMethod: draft.deliveryMethod,
                              defaultClassification: draft.defaultClassification,
                              currency: draft.currency,
                              calendar: draft.calendar,
                              aiPolicy: draft.aiPolicy,
                              qualityGates: draft.qualityGates,
                              enabledAnalysts: draft.enabledAnalysts,
                            })}>
                      {update.isPending ? t('loading') : t('save')}
                    </button>} />

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: 'general', label: 'General' },
        { key: 'analysts', label: 'Analysts', count: (draft.enabledAnalysts ?? DEFAULT_ANALYSTS).length },
        { key: 'policy', label: t('policy') },
        { key: 'calendar', label: 'Calendar' },
        { key: 'gates', label: 'Quality gates' },
        { key: 'members', label: 'Members', count: members.data?.length },
        { key: 'rates', label: 'Rate cards', count: rateCards.data?.length },
      ]} />

      {update.error ? <div className="mb-3"><ErrorBanner error={update.error} /></div> : null}

      {tab === 'general' ? (
        <Section title="Project details">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Name">
              <input className="input" value={draft.name}
                     onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </Field>
            <Field label="Client">
              <input className="input" value={draft.clientName ?? ''}
                     onChange={(event) => setDraft({ ...draft, clientName: event.target.value })} />
            </Field>
            <Field label="Delivery method">
              <select className="input" value={draft.deliveryMethod}
                      onChange={(event) => setDraft({
                        ...draft, deliveryMethod: event.target.value as 'scrum' | 'kanban' })}>
                <option value="scrum">Scrum</option>
                <option value="kanban">Kanban</option>
              </select>
            </Field>
            <Field label="Output language"
                   hint="The generated artifacts use this language regardless of the evidence">
              <select className="input" value={draft.outputLanguage}
                      onChange={(event) => setDraft({
                        ...draft, outputLanguage: event.target.value as 'en' | 'el' })}>
                <option value="en">English</option>
                <option value="el">Ελληνικά</option>
              </select>
            </Field>
            <Field label="Default classification">
              <select className="input" value={draft.defaultClassification}
                      onChange={(event) => setDraft({
                        ...draft,
                        defaultClassification: event.target.value as Project['defaultClassification'],
                      })}>
                <option value="restricted">Restricted</option>
                <option value="confidential">Confidential</option>
                <option value="shareable">Shareable</option>
              </select>
            </Field>
            <Field label="Currency">
              <input className="input" value={draft.currency}
                     onChange={(event) => setDraft({ ...draft, currency: event.target.value })} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Description">
                <textarea className="input h-24" value={draft.description ?? ''}
                          onChange={(event) =>
                            setDraft({ ...draft, description: event.target.value })} />
              </Field>
            </div>
          </div>
        </Section>
      ) : null}

      {tab === 'analysts' ? (
        <Section title="AI analysts"
                 description="Choose which analysts this project's analysis runs use. Changes apply to the next run; runs already started keep their analysts.">
          <AnalystPicker value={draft.enabledAnalysts ?? DEFAULT_ANALYSTS}
                         onChange={(enabledAnalysts) => setDraft({ ...draft, enabledAnalysts })} />
          <div className="mt-3 space-y-2">
            {!(draft.enabledAnalysts ?? DEFAULT_ANALYSTS).includes('qa_analyst')
              && draft.qualityGates.requireTestsForStories ? (
                <Note tone="warning">
                  Without the QA analyst no tests are generated, but the quality gate
                  "require tests for stories" is on: stories need tests written by hand
                  before they can be approved, or switch the gate off under Quality gates.
                </Note>
              ) : null}
            {!(draft.enabledAnalysts ?? DEFAULT_ANALYSTS).includes('business_analyst') ? (
              <Note tone="muted">
                Without the business analyst no new requirements or backlog items are
                proposed; the other analysts work on the backlog that already exists.
              </Note>
            ) : null}
            <Note tone="muted">Save the project to apply the change.</Note>
          </div>
        </Section>
      ) : null}

      {tab === 'policy' ? (
        <div className="space-y-4">
          <Section title="AI and data policy"
                   description="Cloud is disabled by default. A project may be stricter than the deployment, never looser.">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Toggle label="Local only"
                      hint="Blocks every project derived cloud payload"
                      checked={draft.aiPolicy.localOnly}
                      onChange={(value) => setDraft({
                        ...draft,
                        aiPolicy: { ...draft.aiPolicy, localOnly: value,
                                    cloudEnabled: value ? false : draft.aiPolicy.cloudEnabled },
                      })} />
              <Toggle label="Cloud processing permitted"
                      hint="Only minimised, sanitised context may leave"
                      checked={draft.aiPolicy.cloudEnabled}
                      disabled={draft.aiPolicy.localOnly}
                      onChange={(value) => setDraft({
                        ...draft, aiPolicy: { ...draft.aiPolicy, cloudEnabled: value } })} />
              <Field label="Highest classification permitted outward">
                <select className="input" value={draft.aiPolicy.maxCloudClassification}
                        disabled={draft.aiPolicy.localOnly}
                        onChange={(event) => setDraft({
                          ...draft,
                          aiPolicy: {
                            ...draft.aiPolicy,
                            maxCloudClassification:
                              event.target.value as Project['defaultClassification'],
                          },
                        })}>
                  <option value="shareable">Shareable only</option>
                  <option value="confidential">Confidential (sanitised excerpts)</option>
                </select>
              </Field>
              <Toggle label="Sanitise outbound payloads"
                      hint="Reduces disclosure; not a guarantee of anonymisation"
                      checked={draft.aiPolicy.sanitizePayloads}
                      onChange={(value) => setDraft({
                        ...draft, aiPolicy: { ...draft.aiPolicy, sanitizePayloads: value } })} />
              <Toggle label="Local transcription" checked={draft.aiPolicy.localTranscription}
                      onChange={(value) => setDraft({
                        ...draft, aiPolicy: { ...draft.aiPolicy, localTranscription: value } })} />
              <Toggle label="Local embeddings and indexing"
                      checked={draft.aiPolicy.localEmbeddings}
                      onChange={(value) => setDraft({
                        ...draft, aiPolicy: { ...draft.aiPolicy, localEmbeddings: value } })} />
            </div>
          </Section>

          <Section title="What this policy actually means">
            <ul className="space-y-2">
              {(policy.data?.explanation ?? []).map((line) => (
                <li key={line}><Note tone="muted">{line}</Note></li>
              ))}
            </ul>
            <div className="mt-3 space-y-2">
              {(policy.data?.effective ?? []).map((entry, index) => (
                <div key={index} className="rounded border border-ink-200 px-3 py-2 text-xs">
                  <pre className="whitespace-pre-wrap text-ink-700">
                    {JSON.stringify(entry, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </Section>
        </div>
      ) : null}

      {tab === 'calendar' ? (
        <Section title="Working calendar"
                 description="Person days are derived from the project day length; calendar duration also depends on allocation and dependencies.">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Timezone">
              <input className="input" value={draft.calendar.timezone}
                     onChange={(event) => setDraft({
                       ...draft, calendar: { ...draft.calendar, timezone: event.target.value } })} />
            </Field>
            <Field label="Hours per person day">
              <input className="input" type="number" step="0.5"
                     value={draft.calendar.hoursPerPersonDay}
                     onChange={(event) => setDraft({
                       ...draft,
                       calendar: { ...draft.calendar,
                                   hoursPerPersonDay: Number(event.target.value) },
                     })} />
            </Field>
            <Field label="Focus factor"
                   hint="Never applied twice when allocations already represent productive hours">
              <input className="input" type="number" step="0.05" min="0.1" max="1"
                     value={draft.calendar.focusFactor}
                     onChange={(event) => setDraft({
                       ...draft,
                       calendar: { ...draft.calendar, focusFactor: Number(event.target.value) },
                     })} />
            </Field>
          </div>
          <div className="mt-3">
            <Toggle label="Allocations already include the focus factor"
                    checked={draft.calendar.allocationIncludesFocus}
                    onChange={(value) => setDraft({
                      ...draft,
                      calendar: { ...draft.calendar, allocationIncludesFocus: value },
                    })} />
          </div>
        </Section>
      ) : null}

      {tab === 'gates' ? (
        <Section title="Quality gates"
                 description="Critical blockers must be resolved or explicitly waived before a bundle can be approved.">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Toggle label="Require acceptance criteria"
                    checked={draft.qualityGates.requireAcceptanceCriteria}
                    onChange={(value) => setDraft({
                      ...draft,
                      qualityGates: { ...draft.qualityGates, requireAcceptanceCriteria: value },
                    })} />
            <Toggle label="Require a test per story"
                    checked={draft.qualityGates.requireTestsForStories}
                    onChange={(value) => setDraft({
                      ...draft,
                      qualityGates: { ...draft.qualityGates, requireTestsForStories: value },
                    })} />
            <Toggle label="Block on critical findings"
                    checked={draft.qualityGates.blockOnCriticalFindings}
                    onChange={(value) => setDraft({
                      ...draft,
                      qualityGates: { ...draft.qualityGates, blockOnCriticalFindings: value },
                    })} />
            <Toggle label="Block on unresolved critical questions"
                    checked={draft.qualityGates.blockOnUnresolvedCriticalQuestions}
                    onChange={(value) => setDraft({
                      ...draft,
                      qualityGates: {
                        ...draft.qualityGates, blockOnUnresolvedCriticalQuestions: value,
                      },
                    })} />
            <Toggle label="Require client acceptance before publication"
                    hint="Internal readiness approval and client acceptance stay separate records"
                    checked={draft.qualityGates.requireClientAcceptance}
                    onChange={(value) => setDraft({
                      ...draft,
                      qualityGates: { ...draft.qualityGates, requireClientAcceptance: value },
                    })} />
            <Field label="Maximum correction cycles">
              <input className="input" type="number" min={1} max={5}
                     value={draft.qualityGates.maxCorrectionCycles}
                     onChange={(event) => setDraft({
                       ...draft,
                       qualityGates: {
                         ...draft.qualityGates,
                         maxCorrectionCycles: Number(event.target.value),
                       },
                     })} />
            </Field>
          </div>
        </Section>
      ) : null}

      {tab === 'members' ? (
        <Section title="Members"
                 description="Client reviewers see only what a share grant lists."
                 actions={<button type="button" className="btn-secondary"
                                  onClick={() => setInviting(true)}>Add member</button>}>
          <Table
            rows={members.data ?? []}
            rowKey={(row) => row.id}
            columns={[
              { key: 'name', header: 'Person',
                render: (row) => (
                  <div>
                    <p className="font-medium text-ink-900">{row.displayName}</p>
                    <p className="text-xs text-ink-500">{row.email}</p>
                  </div>
                ) },
              { key: 'roles', header: 'Roles',
                render: (row) => (
                  <div className="flex flex-wrap gap-1">
                    {row.roles.map((role) => (
                      <Badge key={role} tone={role === 'client_reviewer' ? 'warning' : 'neutral'}>
                        {role.replace(/_/g, ' ')}
                      </Badge>
                    ))}
                  </div>
                ) },
              { key: 'delivery', header: 'Delivery role',
                render: (row) => row.deliveryRole ?? '—' },
              { key: 'allocation', header: 'Allocation', align: 'right',
                render: (row) => `${row.allocationPercent}%` },
              { key: 'acceptance', header: 'Acceptance authority',
                render: (row) => (row.acceptanceAuthority ? 'Yes' : '—') },
              { key: 'status', header: 'Status',
                render: (row) => row.revokedAt
                  ? <Badge tone="critical">revoked</Badge>
                  : <Badge tone="good">active</Badge> },
            ]} />
        </Section>
      ) : null}

      {tab === 'rates' ? (
        <Section title="Rate cards"
                 description="Effective dated and permission restricted; actual cost uses the rate effective on the work date."
                 actions={<button type="button" className="btn-secondary"
                                  onClick={() => setAddingRateCard(true)}>
                   Add rate card
                 </button>}>
          {rateCards.error ? (
            <Note tone="muted">You do not have permission to read rate cards.</Note>
          ) : (
            <Table
              rows={rateCards.data ?? []}
              rowKey={(row) => row.id}
              empty="No rate card configured yet; cost columns stay empty until one exists."
              columns={[
                { key: 'name', header: 'Name', render: (row) => row.name },
                { key: 'from', header: 'Effective from', render: (row) => row.effectiveFrom },
                { key: 'currency', header: 'Currency', render: (row) => row.currency },
                { key: 'rates', header: 'Rates',
                  render: (row) => (
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(row.rates).map(([role, rate]) => (
                        <Badge key={role} tone="muted">{role}: {rate}</Badge>
                      ))}
                    </div>
                  ) },
                { key: 'contingency', header: 'Contingency', align: 'right',
                  render: (row) => `${row.contingencyPercent}%` },
              ]} />
          )}
        </Section>
      ) : null}

      <AddRateCardModal open={addingRateCard} onClose={() => setAddingRateCard(false)}
                        onCreate={(body) => addRateCard.mutate(body)}
                        busy={addRateCard.isPending} error={addRateCard.error}
                        currency={draft.currency} />

      <InviteModal open={inviting} onClose={() => setInviting(false)}
                   onInvite={(body) => invite.mutate(body)}
                   error={invite.error} busy={invite.isPending} />
    </>
  )
}

function Toggle({ label, hint, checked, onChange, disabled }: {
  label: string; hint?: string; checked: boolean
  onChange: (value: boolean) => void; disabled?: boolean
}) {
  return (
    <label className={`flex items-start gap-2 rounded-lg border border-ink-200 px-3 py-2
                       ${disabled ? 'opacity-50' : ''}`}>
      <input type="checkbox" className="mt-0.5" checked={checked} disabled={disabled}
             onChange={(event) => onChange(event.target.checked)} />
      <span>
        <span className="block text-sm font-medium text-ink-800">{label}</span>
        {hint ? <span className="block text-xs text-ink-500">{hint}</span> : null}
      </span>
    </label>
  )
}

function InviteModal({ open, onClose, onInvite, error, busy }: {
  open: boolean
  onClose: () => void
  onInvite: (body: Record<string, unknown>) => void
  error: unknown
  busy: boolean
}) {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [roles, setRoles] = useState<string[]>(['business_analyst'])
  const [deliveryRole, setDeliveryRole] = useState('')

  return (
    <Modal open={open} title="Add project member" onClose={onClose}
           footer={
             <>
               <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
               <button type="button" className="btn-primary" disabled={busy || !email}
                       onClick={() => onInvite({ email, displayName, roles, deliveryRole })}>
                 Add member
               </button>
             </>
           }>
      <div className="space-y-3">
        <Field label="Email"><input className="input" value={email}
          onChange={(event) => setEmail(event.target.value)} /></Field>
        <Field label="Display name"><input className="input" value={displayName}
          onChange={(event) => setDisplayName(event.target.value)} /></Field>
        <Field label="Delivery role" hint="Used for capacity and rate resolution">
          <input className="input" value={deliveryRole}
                 onChange={(event) => setDeliveryRole(event.target.value)} />
        </Field>
        <fieldset>
          <legend className="label mb-1">Roles</legend>
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {ROLES.map((role) => (
              <label key={role} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={roles.includes(role)}
                       onChange={(event) => setRoles(event.target.checked
                         ? [...roles, role]
                         : roles.filter((value) => value !== role))} />
                {role.replace(/_/g, ' ')}
              </label>
            ))}
          </div>
        </fieldset>
        {roles.includes('client_reviewer') ? (
          <Note tone="warning">
            A client reviewer holds no project wide read permission. Everything they see
            comes from an explicit share grant.
          </Note>
        ) : null}
        {error ? <ErrorBanner error={error} /> : null}
      </div>
    </Modal>
  )
}
