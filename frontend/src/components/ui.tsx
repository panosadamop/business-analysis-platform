/** Shared interface primitives. Desktop first, keyboard reachable, WCAG oriented. */
import { cloneElement, isValidElement, useEffect, useId, useRef } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, ReactElement, ReactNode } from 'react'

import { ApiError } from '../lib/api'

const APP_TITLE = 'AI Analysis Team'

export function PageHeader({
  title, subtitle, actions,
}: { title: string; subtitle?: string; actions?: ReactNode }) {
  // Every screen has a descriptive document title (WCAG 2.4.2).
  useEffect(() => {
    document.title = `${title} · ${APP_TITLE}`
  }, [title])

  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-ink-900">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-ink-500" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-300
                       border-t-brand-600" aria-hidden />
      {label}
    </div>
  )
}

export function EmptyState({ title, hint, action }: {
  title: string; hint?: string; action?: ReactNode
}) {
  return (
    <div className="card card-pad text-center">
      <p className="text-sm font-medium text-ink-700">{title}</p>
      {hint ? <p className="mx-auto mt-1 max-w-prose text-sm text-ink-500">{hint}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  )
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null
  const details = api?.details as Record<string, unknown> | null
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm">
      <p className="font-medium text-red-800">
        {api?.message ?? (error instanceof Error ? error.message : 'Something went wrong')}
      </p>
      {api?.code ? <p className="mt-0.5 text-xs text-red-700">Code: {api.code}</p> : null}
      {details ? (
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-surface/70 p-2 text-xs
                        text-red-900">{JSON.stringify(details, null, 2)}</pre>
      ) : null}
      {onRetry ? (
        <button type="button" className="btn-secondary mt-2 text-xs" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}

const TONES: Record<string, string> = {
  neutral: 'bg-ink-100 text-ink-700 border-ink-200',
  info: 'bg-brand-50 text-brand-800 border-brand-200',
  good: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  warning: 'bg-amber-50 text-amber-800 border-amber-200',
  critical: 'bg-red-50 text-red-800 border-red-200',
  muted: 'bg-surface text-ink-500 border-ink-200',
}

export function Badge({ children, tone = 'neutral', icon }: {
  children: ReactNode; tone?: keyof typeof TONES | string; icon?: string
}) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5
                      text-xs font-medium ${TONES[tone] ?? TONES.neutral}`}>
      {icon ? <span aria-hidden>{icon}</span> : null}
      {children}
    </span>
  )
}

const STATE_TONES: Record<string, { tone: string; icon: string }> = {
  draft: { tone: 'neutral', icon: '✎' },
  in_review: { tone: 'info', icon: '👁' },
  approved: { tone: 'good', icon: '✓' },
  rejected: { tone: 'critical', icon: '✕' },
  superseded: { tone: 'muted', icon: '⤓' },
  archived: { tone: 'muted', icon: '📦' },
}

export function StateBadge({ state }: { state: string }) {
  const config = STATE_TONES[state] ?? { tone: 'neutral', icon: '•' }
  return <Badge tone={config.tone} icon={config.icon}>{state.replace('_', ' ')}</Badge>
}

const SEVERITY_TONES: Record<string, { tone: string; icon: string }> = {
  critical: { tone: 'critical', icon: '⛔' },
  major: { tone: 'warning', icon: '⚠' },
  minor: { tone: 'info', icon: 'ℹ' },
  info: { tone: 'muted', icon: 'ℹ' },
}

export function SeverityBadge({ severity }: { severity: string }) {
  const config = SEVERITY_TONES[severity] ?? SEVERITY_TONES.info
  return <Badge tone={config.tone} icon={config.icon}>{severity}</Badge>
}

export function ProvenanceBadge({ provenance }: { provenance: string }) {
  const map: Record<string, { tone: string; label: string; icon: string }> = {
    evidence: { tone: 'good', label: 'evidence backed', icon: '🔗' },
    assumption: { tone: 'warning', label: 'analyst assumption', icon: '≈' },
    ai_suggestion: { tone: 'info', label: 'AI proposal', icon: '✧' },
    client_decision: { tone: 'good', label: 'client decision', icon: '✓' },
  }
  const config = map[provenance] ?? map.assumption
  return <Badge tone={config.tone} icon={config.icon}>{config.label}</Badge>
}

export function Section({ title, description, actions, children }: {
  title: string; description?: string; actions?: ReactNode; children: ReactNode
}) {
  return (
    <section className="card card-pad">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
          {description ? <p className="text-xs text-ink-500">{description}</p> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  )
}

/**
 * A labelled form control. A single control child is wired to the hint with
 * aria-describedby, so the hint is announced as a description rather than
 * folded into the accessible name.
 */
export function Field({ label, hint, children }: {
  label: string; hint?: string; children: ReactNode
}) {
  const hintId = useId()
  const control = hint && isValidElement(children)
    ? cloneElement(children as ReactElement<{ 'aria-describedby'?: string }>, {
        'aria-describedby': [
          (children as ReactElement<{ 'aria-describedby'?: string }>).props['aria-describedby'],
          hintId,
        ].filter(Boolean).join(' '),
      })
    : children
  return (
    <div>
      <label className="block">
        <span className="label mb-1">{label}</span>
        {control}
      </label>
      {hint ? <p id={hintId} className="mt-1 text-xs text-ink-500">{hint}</p> : null}
    </div>
  )
}

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * Dialog behaviour shared by every modal (WCAG 2.1.2, 2.4.3): focus moves into
 * the dialog when it opens, Tab and Shift+Tab stay inside it, Escape closes it,
 * and focus returns to the control that opened it.
 */
function useDialog<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const ref = useRef<T>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    const node = ref.current
    const first = node?.querySelector<HTMLElement>(
      '[data-autofocus], input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])')
    ;(first ?? node)?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !node) return
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter((item) => !item.closest('[hidden], [aria-hidden="true"]'))
      if (!items.length) {
        event.preventDefault()
        node.focus()
        return
      }
      const firstItem = items[0]
      const lastItem = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === firstItem || active === node)) {
        event.preventDefault()
        lastItem.focus()
      } else if (!event.shiftKey && active === lastItem) {
        event.preventDefault()
        firstItem.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (opener && document.contains(opener)) opener.focus()
    }
  }, [open])

  return ref
}

export function Modal({ open, title, onClose, children, footer, wide }: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  const ref = useDialog<HTMLDivElement>(open, onClose)
  const titleId = useId()

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto
                    bg-ink-950/40 p-2 sm:p-8">
      <div ref={ref} tabIndex={-1}
           role="dialog" aria-modal="true" aria-labelledby={titleId}
           className={`card w-full ${wide ? 'max-w-5xl' : 'max-w-2xl'} outline-none`}>
        <div className="flex items-center justify-between border-b border-ink-200 px-5 py-3">
          <h2 id={titleId} className="text-sm font-semibold text-ink-900">{title}</h2>
          <button type="button" className="btn-ghost" onClick={onClose} aria-label="Close">
            <span aria-hidden>✕</span>
          </button>
        </div>
        <div className="max-h-[calc(100dvh-9rem)] overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-5">
          {children}
        </div>
        {footer ? (
          <div className="flex flex-wrap justify-end gap-2 border-t border-ink-200 px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/**
 * A modal that submits a form: used by every "add an entry by hand" dialog.
 *
 * Submitting is the form's own action, so Enter works and the browser applies
 * required field validation before the request is sent.
 */
export function CreateModal({
  open, title, onClose, onSubmit, busy, error, children,
  submitLabel = 'Create', wide,
}: {
  open: boolean
  title: string
  onClose: () => void
  onSubmit: () => void
  busy?: boolean
  error?: unknown
  children: ReactNode
  submitLabel?: string
  wide?: boolean
}) {
  const ref = useDialog<HTMLFormElement>(open, onClose)
  const titleId = useId()

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto
                    bg-ink-950/40 p-2 sm:p-8">
      <form
        ref={ref}
        tabIndex={-1}
        role="dialog" aria-modal="true" aria-labelledby={titleId}
        className={`card w-full ${wide ? 'max-w-4xl' : 'max-w-2xl'} outline-none`}
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        <div className="flex items-center justify-between border-b border-ink-200
                        px-5 py-3">
          <h2 id={titleId} className="text-sm font-semibold text-ink-900">{title}</h2>
          <button type="button" className="btn-ghost" onClick={onClose}
                  aria-label="Close"><span aria-hidden>✕</span></button>
        </div>
        <div className="max-h-[calc(100dvh-9rem)] space-y-3 overflow-y-auto px-4 py-4
                        sm:max-h-[70vh] sm:px-5">
          {children}
          {error ? <ErrorBanner error={error} /> : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-ink-200 px-5 py-3">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Saving…' : submitLabel}
          </button>
        </div>
      </form>
    </div>
  )
}

export function Table<T>({ columns, rows, empty, rowKey, onRowClick }: {
  columns: { key: string; header: string; render: (row: T) => ReactNode; align?: 'right' }[]
  rows: T[]
  empty?: string
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
}) {
  if (!rows.length) {
    return <p className="px-3 py-6 text-center text-sm text-ink-500">{empty ?? 'Nothing to show'}</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full">
        <thead>
          <tr className="border-b border-ink-200">
            {columns.map((column) => (
              <th key={column.key}
                  className={`th ${column.align === 'right' ? 'text-right' : ''}`}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}
                className={`border-b border-ink-100 last:border-0 ${
                  onRowClick ? 'cursor-pointer hover:bg-ink-50 focus-visible:bg-brand-50' : ''}`}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                // Clickable rows are reachable and operable from the keyboard (2.1.1).
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={onRowClick ? (event) => {
                  if (event.target !== event.currentTarget) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onRowClick(row)
                  }
                } : undefined}>
              {columns.map((column) => (
                <td key={column.key}
                    className={`td ${column.align === 'right' ? 'text-right tabular-nums' : ''}`}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Tabs({ tabs, active, onChange }: {
  tabs: { key: string; label: string; count?: number }[]
  active: string
  onChange: (key: string) => void
}) {
  // Tablist keyboard model: one tab stop, arrow keys, Home and End move between tabs.
  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const index = tabs.findIndex((tab) => tab.key === active)
    const next = {
      ArrowRight: index + 1, ArrowDown: index + 1,
      ArrowLeft: index - 1, ArrowUp: index - 1,
      Home: 0, End: tabs.length - 1,
    }[event.key]
    if (next === undefined || !tabs.length) return
    event.preventDefault()
    const targetIndex = (next + tabs.length) % tabs.length
    onChange(tabs[targetIndex].key)
    event.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')[targetIndex]?.focus()
  }

  return (
    <div className="mb-4 flex flex-wrap gap-1 border-b border-ink-200" role="tablist"
         onKeyDown={onKeyDown}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={active === tab.key}
          tabIndex={active === tab.key ? 0 : -1}
          onClick={() => onChange(tab.key)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
            active === tab.key
              ? 'border-brand-600 text-brand-700'
              : 'border-transparent text-ink-600 hover:text-ink-800'
          }`}
        >
          {tab.label}
          {tab.count !== undefined ? (
            <span className="ml-1.5 rounded-full bg-ink-100 px-1.5 text-xs text-ink-600">
              {tab.count}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  )
}

export function Note({ children, tone = 'info' }: { children: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    info: 'border-brand-200 bg-brand-50 text-brand-900',
    warning: 'border-amber-200 bg-amber-50 text-amber-900',
    critical: 'border-red-200 bg-red-50 text-red-900',
    muted: 'border-ink-200 bg-ink-50 text-ink-700',
  }
  return (
    <p className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${tones[tone] ?? tones.info}`}>
      {children}
    </p>
  )
}

export function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}

export function formatDateTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export function money(value?: { amount: string; currency: string } | null) {
  if (!value) return '—'
  const amount = Number(value.amount)
  return `${amount.toLocaleString(undefined, { minimumFractionDigits: 2,
    maximumFractionDigits: 2 })} ${value.currency}`
}
