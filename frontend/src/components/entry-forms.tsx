/**
 * Forms for authoring an entry by hand.
 *
 * Everything the analyst workflow can generate can also be written manually: a
 * requirement, a question, a glossary term, a specification, a test case, a
 * sprint, a milestone, an allocation, a rate card and an evidence link. They
 * live together so the wording and the provenance rules stay consistent
 * wherever an entry is created.
 */
import { useState } from 'react'

import { CreateModal, Field, Note } from './ui'
import type { BacklogNode, SourceView } from '../types'

export interface EntryFormProps {
  open: boolean
  onClose: () => void
  onCreate: (body: Record<string, unknown>) => void
  busy: boolean
  error: unknown
}

const REQUIREMENT_TYPES = [
  'business', 'functional', 'non_functional', 'technical', 'constraint',
  'business_rule', 'assumption', 'decision', 'goal', 'stakeholder',
  'scope_boundary', 'ux', 'data',
]

const PRIORITIES = ['critical', 'high', 'medium', 'low']

export function AddRequirementModal({ open, onClose, onCreate, busy, error }: EntryFormProps) {
  const [form, setForm] = useState({
    title: '', statement: '', rationale: '', type: 'business',
    priority: 'medium', provenance: 'evidence', confidence: '0.8',
  })

  return (
    <CreateModal open={open} title="Add a requirement" onClose={onClose} busy={busy}
                 error={error} submitLabel="Add requirement"
                 onSubmit={() => onCreate({ ...form, confidence: Number(form.confidence) })}>
      <Field label="Title">
        <input className="input" required value={form.title}
               onChange={(event) => setForm({ ...form, title: event.target.value })} />
      </Field>
      <Field label="Statement" hint="Write the obligation as the evidence states it">
        <textarea className="input h-24" required value={form.statement}
                  onChange={(event) => setForm({ ...form, statement: event.target.value })} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Type">
          <select className="input" value={form.type}
                  onChange={(event) => setForm({ ...form, type: event.target.value })}>
            {REQUIREMENT_TYPES.map((value) => (
              <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </Field>
        <Field label="Priority">
          <select className="input" value={form.priority}
                  onChange={(event) => setForm({ ...form, priority: event.target.value })}>
            {PRIORITIES.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </Field>
        <Field label="Provenance" hint="How this statement is supported">
          <select className="input" value={form.provenance}
                  onChange={(event) => setForm({ ...form, provenance: event.target.value })}>
            <option value="evidence">Evidence backed</option>
            <option value="assumption">Analyst assumption</option>
            <option value="client_decision">Client decision</option>
          </select>
        </Field>
      </div>
      <Field label="Rationale">
        <input className="input" value={form.rationale}
               onChange={(event) => setForm({ ...form, rationale: event.target.value })} />
      </Field>
      <Note tone="muted">
        A hand written requirement carries the provenance you choose. Link it to a source
        afterwards so the claim resolves to a real evidence locator.
      </Note>
    </CreateModal>
  )
}

export function AddQuestionModal({ open, onClose, onCreate, busy, error }: EntryFormProps) {
  const [form, setForm] = useState({
    title: '', detail: '', kind: 'ambiguity', severity: 'major',
    proposedClarification: '', clientVisible: false,
  })

  return (
    <CreateModal open={open} title="Raise a question" onClose={onClose} busy={busy}
                 error={error} submitLabel="Raise question"
                 onSubmit={() => onCreate(form)}>
      <Field label="Question">
        <input className="input" required value={form.title}
               onChange={(event) => setForm({ ...form, title: event.target.value })} />
      </Field>
      <Field label="Detail">
        <textarea className="input h-20" required value={form.detail}
                  onChange={(event) => setForm({ ...form, detail: event.target.value })} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Kind">
          <select className="input" value={form.kind}
                  onChange={(event) => setForm({ ...form, kind: event.target.value })}>
            {['ambiguity', 'contradiction', 'duplicate', 'missing_rule',
              'incomplete_flow', 'design_behaviour', 'dependency', 'other'].map((value) => (
                <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </Field>
        <Field label="Severity" hint="A critical question blocks approval until resolved">
          <select className="input" value={form.severity}
                  onChange={(event) => setForm({ ...form, severity: event.target.value })}>
            {['critical', 'major', 'minor', 'info'].map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Proposed clarification">
        <input className="input" value={form.proposedClarification}
               onChange={(event) =>
                 setForm({ ...form, proposedClarification: event.target.value })} />
      </Field>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.clientVisible}
               onChange={(event) =>
                 setForm({ ...form, clientVisible: event.target.checked })} />
        Visible to the client in their workspace
      </label>
    </CreateModal>
  )
}

export function AddTermModal({ open, onClose, onCreate, busy, error }: EntryFormProps) {
  const [form, setForm] = useState({ term: '', definition: '', language: 'en',
                                     translation: '' })

  return (
    <CreateModal open={open} title="Add a glossary term" onClose={onClose} busy={busy}
                 error={error} submitLabel="Add term"
                 onSubmit={() => onCreate({
                   term: form.term,
                   definition: form.definition,
                   language: form.language,
                   translations: form.translation
                     ? { [form.language === 'en' ? 'el' : 'en']: form.translation }
                     : {},
                 })}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Term">
          <input className="input" required value={form.term}
                 onChange={(event) => setForm({ ...form, term: event.target.value })} />
        </Field>
        <Field label="Language">
          <select className="input" value={form.language}
                  onChange={(event) => setForm({ ...form, language: event.target.value })}>
            <option value="en">English</option>
            <option value="el">Ελληνικά</option>
          </select>
        </Field>
      </div>
      <Field label="Definition">
        <textarea className="input h-20" required value={form.definition}
                  onChange={(event) => setForm({ ...form, definition: event.target.value })} />
      </Field>
      <Field label={form.language === 'en' ? 'Greek wording' : 'English wording'}
             hint="Stored as a translation of the same term, not a second entry">
        <input className="input" value={form.translation}
               onChange={(event) => setForm({ ...form, translation: event.target.value })} />
      </Field>
    </CreateModal>
  )
}

export function AddSpecificationModal({ open, onClose, onCreate, busy, error }: EntryFormProps) {
  const [form, setForm] = useState({ kind: 'functional', title: '', body: '',
                                     diagramSource: '', structured: '' })
  const [jsonError, setJsonError] = useState<string | null>(null)

  const isDiagram = form.kind === 'process_diagram'
  const isStructured = form.kind === 'data_model' || form.kind === 'api'

  return (
    <CreateModal open={open} title="Write a specification" onClose={onClose} busy={busy}
                 error={error ?? jsonError} submitLabel="Create specification"
                 wide
                 onSubmit={() => {
                   let structured: Record<string, unknown> = {}
                   if (isStructured && form.structured.trim()) {
                     try {
                       structured = JSON.parse(form.structured)
                     } catch (caught) {
                       setJsonError(`The structured content is not valid JSON: ${caught}`)
                       return
                     }
                   }
                   setJsonError(null)
                   onCreate({
                     kind: form.kind, title: form.title,
                     body: isDiagram || isStructured ? null : form.body,
                     diagramSource: isDiagram ? form.diagramSource : null,
                     structured,
                   })
                 }}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Kind">
          <select className="input" value={form.kind}
                  onChange={(event) => setForm({ ...form, kind: event.target.value })}>
            <option value="functional">Functional</option>
            <option value="non_functional">Non functional</option>
            <option value="process_diagram">Process diagram</option>
            <option value="data_model">Data model</option>
            <option value="api">API specification</option>
            <option value="ux">UX specification</option>
            <option value="data">Data specification</option>
          </select>
        </Field>
        <Field label="Title">
          <input className="input" required value={form.title}
                 onChange={(event) => setForm({ ...form, title: event.target.value })} />
        </Field>
      </div>

      {isDiagram ? (
        <Field label="Mermaid source" hint="Main, alternate and error flows">
          <textarea className="input h-48 font-mono text-base sm:text-xs" required
                    placeholder={'flowchart TD\n  start([Start]) --> check{Allowed?}'}
                    value={form.diagramSource}
                    onChange={(event) =>
                      setForm({ ...form, diagramSource: event.target.value })} />
        </Field>
      ) : isStructured ? (
        <Field label="Structured content"
               hint={form.kind === 'api'
                 ? 'An OpenAPI document as JSON'
                 : 'Entities, fields, relationships and privacy classification as JSON'}>
          <textarea className="input h-48 font-mono text-base sm:text-xs" required
                    value={form.structured}
                    onChange={(event) =>
                      setForm({ ...form, structured: event.target.value })} />
        </Field>
      ) : (
        <Field label="Body"
               hint="Markdown: scope, actors, flows, rules, permissions, validations, exceptions">
          <textarea className="input h-48" required value={form.body}
                    onChange={(event) => setForm({ ...form, body: event.target.value })} />
        </Field>
      )}

      <Note tone="muted">
        A specification you write is a draft like any other. It needs human approval
        before it can be shared or published.
      </Note>
    </CreateModal>
  )
}

export function AddTestCaseModal({ open, onClose, onCreate, busy, error, stories }:
  EntryFormProps & { stories: BacklogNode[] }) {
  const [form, setForm] = useState({
    title: '', objective: '', storyId: '', testType: 'positive', priority: 'medium',
    preconditions: '', steps: '', expectedResults: '', gherkinText: '',
  })

  return (
    <CreateModal open={open} title="Write a test case" onClose={onClose} busy={busy}
                 error={error} submitLabel="Create test case" wide
                 onSubmit={() => onCreate({
                   title: form.title,
                   objective: form.objective || null,
                   storyId: form.storyId || null,
                   testType: form.testType,
                   priority: form.priority,
                   preconditions: form.preconditions.split('\n').filter(Boolean),
                   steps: form.steps.split('\n').filter(Boolean).map((line, index) => {
                     const [action, expected] = line.split('=>')
                     return { ordinal: index + 1, action: (action ?? '').trim(),
                              expected: expected ? expected.trim() : null }
                   }),
                   expectedResults: form.expectedResults.split('\n').filter(Boolean),
                   gherkinText: form.gherkinText || null,
                 })}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Title">
          <input className="input" required value={form.title}
                 onChange={(event) => setForm({ ...form, title: event.target.value })} />
        </Field>
        <Field label="Story" hint="Linking a story is what gives the test its coverage">
          <select className="input" value={form.storyId}
                  onChange={(event) => setForm({ ...form, storyId: event.target.value })}>
            <option value="">Not linked yet</option>
            {stories.map((story) => (
              <option key={story.id} value={story.id}>
                {story.stableId} — {story.title}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Objective">
        <input className="input" value={form.objective}
               onChange={(event) => setForm({ ...form, objective: event.target.value })} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Type">
          <select className="input" value={form.testType}
                  onChange={(event) => setForm({ ...form, testType: event.target.value })}>
            {['positive', 'negative', 'boundary', 'validation', 'permissions',
              'integration', 'non_functional', 'end_to_end', 'acceptance'].map((value) => (
                <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </Field>
        <Field label="Priority">
          <select className="input" value={form.priority}
                  onChange={(event) => setForm({ ...form, priority: event.target.value })}>
            {PRIORITIES.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Preconditions" hint="One per line">
        <textarea className="input h-16" value={form.preconditions}
                  onChange={(event) =>
                    setForm({ ...form, preconditions: event.target.value })} />
      </Field>
      <Field label="Steps" hint="One per line, as: action => expected result">
        <textarea className="input h-20" value={form.steps}
                  onChange={(event) => setForm({ ...form, steps: event.target.value })} />
      </Field>
      <Field label="Expected results" hint="One per line">
        <textarea className="input h-16" value={form.expectedResults}
                  onChange={(event) =>
                    setForm({ ...form, expectedResults: event.target.value })} />
      </Field>
      <Field label="Gherkin"
             hint="Optional. Validated before the test is saved; invalid syntax is refused.">
        <textarea className="input h-32 font-mono text-base sm:text-xs" value={form.gherkinText}
                  placeholder={'@negative\nFeature: Invoice access\n'
                    + '  Scenario: Inactive account\n'
                    + '    Given an inactive customer account\n'
                    + '    When the invoice list is opened\n'
                    + '    Then access is refused'}
                  onChange={(event) =>
                    setForm({ ...form, gherkinText: event.target.value })} />
      </Field>
      <Note tone="muted">
        The test is saved awaiting review. Generation and hand authoring both leave a
        draft; neither records a run status.
      </Note>
    </CreateModal>
  )
}

export function AddSprintModal({ open, onClose, onCreate, busy, error }: EntryFormProps) {
  const [form, setForm] = useState({ name: '', goal: '', startDate: '', endDate: '',
                                     team: 'default', capacityHours: '0' })

  return (
    <CreateModal open={open} title="Add a sprint" onClose={onClose} busy={busy}
                 error={error} submitLabel="Add sprint"
                 onSubmit={() => onCreate({ ...form,
                                            capacityHours: Number(form.capacityHours) })}>
      <Field label="Name">
        <input className="input" required value={form.name}
               onChange={(event) => setForm({ ...form, name: event.target.value })} />
      </Field>
      <Field label="Goal">
        <input className="input" value={form.goal}
               onChange={(event) => setForm({ ...form, goal: event.target.value })} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Start date">
          <input className="input" type="date" required value={form.startDate}
                 onChange={(event) => setForm({ ...form, startDate: event.target.value })} />
        </Field>
        <Field label="End date">
          <input className="input" type="date" required value={form.endDate}
                 onChange={(event) => setForm({ ...form, endDate: event.target.value })} />
        </Field>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Team" hint="Story points are only comparable within one team">
          <input className="input" value={form.team}
                 onChange={(event) => setForm({ ...form, team: event.target.value })} />
        </Field>
        <Field label="Capacity (person hours)">
          <input className="input" type="number" min="0" value={form.capacityHours}
                 onChange={(event) =>
                   setForm({ ...form, capacityHours: event.target.value })} />
        </Field>
      </div>
    </CreateModal>
  )
}

export function AddMilestoneModal({ open, onClose, onCreate, busy, error }: EntryFormProps) {
  const [form, setForm] = useState({ name: '', dueDate: '', baselineDate: '',
                                     forecastDate: '', note: '' })

  return (
    <CreateModal open={open} title="Add a milestone" onClose={onClose} busy={busy}
                 error={error} submitLabel="Add milestone"
                 onSubmit={() => onCreate({
                   name: form.name, dueDate: form.dueDate,
                   baselineDate: form.baselineDate || null,
                   forecastDate: form.forecastDate || null,
                   note: form.note || null,
                 })}>
      <Field label="Name">
        <input className="input" required value={form.name}
               onChange={(event) => setForm({ ...form, name: event.target.value })} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Due date">
          <input className="input" type="date" required value={form.dueDate}
                 onChange={(event) => setForm({ ...form, dueDate: event.target.value })} />
        </Field>
        <Field label="Baseline date" hint="The agreed date, kept for comparison">
          <input className="input" type="date" value={form.baselineDate}
                 onChange={(event) =>
                   setForm({ ...form, baselineDate: event.target.value })} />
        </Field>
        <Field label="Forecast date">
          <input className="input" type="date" value={form.forecastDate}
                 onChange={(event) =>
                   setForm({ ...form, forecastDate: event.target.value })} />
        </Field>
      </div>
      <Field label="Note">
        <input className="input" value={form.note}
               onChange={(event) => setForm({ ...form, note: event.target.value })} />
      </Field>
    </CreateModal>
  )
}

export function AddAllocationModal({ open, onClose, onCreate, busy, error, people }:
  EntryFormProps & { people: { userId: string; displayName: string }[] }) {
  const [form, setForm] = useState({ userId: '', role: '', startDate: '', endDate: '',
                                     percent: '100' })

  return (
    <CreateModal open={open} title="Allocate a person" onClose={onClose} busy={busy}
                 error={error} submitLabel="Add allocation"
                 onSubmit={() => onCreate({ ...form, percent: Number(form.percent) })}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Person">
          <select className="input" required value={form.userId}
                  onChange={(event) => setForm({ ...form, userId: event.target.value })}>
            <option value="">Select…</option>
            {people.map((person) => (
              <option key={person.userId} value={person.userId}>
                {person.displayName}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Delivery role" hint="Used to resolve the rate and the capacity">
          <input className="input" required value={form.role}
                 onChange={(event) => setForm({ ...form, role: event.target.value })} />
        </Field>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="From">
          <input className="input" type="date" required value={form.startDate}
                 onChange={(event) => setForm({ ...form, startDate: event.target.value })} />
        </Field>
        <Field label="To">
          <input className="input" type="date" required value={form.endDate}
                 onChange={(event) => setForm({ ...form, endDate: event.target.value })} />
        </Field>
        <Field label="Percent">
          <input className="input" type="number" min="1" max="100" value={form.percent}
                 onChange={(event) => setForm({ ...form, percent: event.target.value })} />
        </Field>
      </div>
      <Note tone="muted">
        Allocation across projects is checked: a person over the configured capacity is
        reported rather than silently overbooked.
      </Note>
    </CreateModal>
  )
}

export function AddRateCardModal({ open, onClose, onCreate, busy, error, currency }:
  EntryFormProps & { currency: string }) {
  const [form, setForm] = useState({
    name: '', effectiveFrom: '', effectiveTo: '', contingencyPercent: '0',
    rates: 'analysis:85\nengineering:95\nqa:75\ndelivery:110',
  })

  return (
    <CreateModal open={open} title="Add a rate card" onClose={onClose} busy={busy}
                 error={error} submitLabel="Add rate card"
                 onSubmit={() => onCreate({
                   name: form.name,
                   currency,
                   effectiveFrom: form.effectiveFrom,
                   effectiveTo: form.effectiveTo || null,
                   contingencyPercent: Number(form.contingencyPercent),
                   rates: Object.fromEntries(
                     form.rates.split('\n').filter(Boolean).map((line) => {
                       const [role, rate] = line.split(':')
                       return [(role ?? '').trim(), (rate ?? '0').trim()]
                     })),
                 })}>
      <Field label="Name">
        <input className="input" required value={form.name}
               onChange={(event) => setForm({ ...form, name: event.target.value })} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Effective from">
          <input className="input" type="date" required value={form.effectiveFrom}
                 onChange={(event) =>
                   setForm({ ...form, effectiveFrom: event.target.value })} />
        </Field>
        <Field label="Effective to" hint="Leave empty while it is the current card">
          <input className="input" type="date" value={form.effectiveTo}
                 onChange={(event) =>
                   setForm({ ...form, effectiveTo: event.target.value })} />
        </Field>
        <Field label="Contingency %">
          <input className="input" type="number" min="0" value={form.contingencyPercent}
                 onChange={(event) =>
                   setForm({ ...form, contingencyPercent: event.target.value })} />
        </Field>
      </div>
      <Field label={`Rates in ${currency}`} hint="One per line, as: role:hourly rate">
        <textarea className="input h-28 font-mono text-base sm:text-xs" value={form.rates}
                  onChange={(event) => setForm({ ...form, rates: event.target.value })} />
      </Field>
      <Note tone="muted">
        Rate cards are effective dated. Actual cost always uses the rate in force on the
        work date, not the newest card.
      </Note>
    </CreateModal>
  )
}

export function AddEvidenceLinkModal({ open, onClose, onCreate, busy, error, sources,
                                       targetType, targetLabel }:
  EntryFormProps & {
    sources: SourceView[]
    targetType: string
    targetLabel: string
  }) {
  const [form, setForm] = useState({ sourceVersionId: '', locatorKind: 'paragraph',
                                     locatorValue: '', linkType: 'derived_from',
                                     rationale: '' })

  return (
    <CreateModal open={open} title={`Link evidence to ${targetLabel}`} onClose={onClose}
                 busy={busy} error={error} submitLabel="Link evidence"
                 onSubmit={() => onCreate({ ...form, targetType })}>
      <Field label="Source">
        <select className="input" required value={form.sourceVersionId}
                onChange={(event) =>
                  setForm({ ...form, sourceVersionId: event.target.value })}>
          <option value="">Select a source…</option>
          {sources.filter((source) => !source.accessRestricted
                                      && source.currentVersionId).map((source) => (
            <option key={source.id} value={source.currentVersionId ?? ''}>
              {source.title} (v{source.currentVersion})
            </option>
          ))}
        </select>
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Locator kind">
          <select className="input" value={form.locatorKind}
                  onChange={(event) =>
                    setForm({ ...form, locatorKind: event.target.value })}>
            {['paragraph', 'page', 'cell_range', 'timestamp', 'row', 'schema_path',
              'node'].map((value) => (
                <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </Field>
        <Field label="Locator value"
               hint="For example Scope#p3, Sheet1!A4:C4 or t:12000">
          <input className="input" required value={form.locatorValue}
                 onChange={(event) =>
                   setForm({ ...form, locatorValue: event.target.value })} />
        </Field>
      </div>
      <Field label="Link type">
        <select className="input" value={form.linkType}
                onChange={(event) => setForm({ ...form, linkType: event.target.value })}>
          {['derived_from', 'verifies', 'implements', 'references', 'contradicts',
            'duplicates'].map((value) => (
              <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </Field>
      <Field label="Rationale">
        <input className="input" value={form.rationale}
               onChange={(event) => setForm({ ...form, rationale: event.target.value })} />
      </Field>
      <Note tone="muted">
        This is what turns a stated claim into an evidence backed one: the source viewer
        opens at the locator you give here.
      </Note>
    </CreateModal>
  )
}
