/** The AI analyst stages a project can use, and a picker for choosing them. */
import type { AnalystRole } from '../types'

/** In run order: each analyst builds on what the earlier ones produced. */
export const ANALYSTS: { role: AnalystRole; label: string; produces: string }[] = [
  { role: 'business_analyst', label: 'Business analyst',
    produces: 'Requirements, open questions, glossary, the epic to story backlog and functional specifications' },
  { role: 'ux_analyst', label: 'UX analyst',
    produces: 'Personas, user journeys, screens with every state to design, usability and accessibility requirements' },
  { role: 'data_analyst', label: 'Data analyst',
    produces: 'Data quality rules, reporting metrics, retention and deletion of personal data, migration notes' },
  { role: 'technical_analyst', label: 'Technical analyst',
    produces: 'Non functional requirements, process diagrams, data and API models and role effort estimates' },
  { role: 'qa_analyst', label: 'QA analyst',
    produces: 'Test cases with Gherkin for every story and review findings on gaps and contradictions' },
]

export const ALL_ANALYSTS: AnalystRole[] = ANALYSTS.map((analyst) => analyst.role)

/** What a project uses unless someone chooses otherwise; UX and data are opt in. */
export const DEFAULT_ANALYSTS: AnalystRole[] =
  ['business_analyst', 'technical_analyst', 'qa_analyst']

export function analystLabel(role: string) {
  return ANALYSTS.find((analyst) => analyst.role === role)?.label ?? role
}

/** The chosen analysts, always in run order. */
export function sortAnalysts(roles: AnalystRole[]) {
  return ALL_ANALYSTS.filter((role) => roles.includes(role))
}

export function AnalystPicker({ value, onChange, disabled }: {
  value: AnalystRole[]
  onChange: (value: AnalystRole[]) => void
  disabled?: boolean
}) {
  return (
    <fieldset>
      <legend className="label mb-1">Analysts</legend>
      <p id="analyst-picker-hint" className="mb-2 text-xs text-ink-500">
        An analysis run uses the analysts chosen here, in this order. At least one is needed.
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {ANALYSTS.map((analyst) => {
          const checked = value.includes(analyst.role)
          // The last remaining analyst cannot be switched off.
          const locked = checked && value.length === 1
          return (
            <label key={analyst.role}
                   className={`flex items-start gap-2 rounded-lg border px-3 py-2 ${
                     checked ? 'border-brand-200 bg-brand-50' : 'border-ink-200'} ${
                     disabled || locked ? 'cursor-not-allowed' : 'cursor-pointer'}`}>
              <input type="checkbox" className="mt-0.5" checked={checked}
                     disabled={disabled || locked}
                     aria-describedby="analyst-picker-hint"
                     onChange={(event) => onChange(sortAnalysts(event.target.checked
                       ? [...value, analyst.role]
                       : value.filter((role) => role !== analyst.role)))} />
              <span>
                <span className="block text-sm font-medium text-ink-800">{analyst.label}</span>
                <span className="block text-xs text-ink-500">{analyst.produces}</span>
                {locked ? (
                  <span className="mt-1 block text-xs text-ink-600">
                    The only analyst left; choose another first to switch this one off.
                  </span>
                ) : null}
              </span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
