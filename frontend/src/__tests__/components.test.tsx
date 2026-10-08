/** Interface primitives, charts and internationalisation. */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  BarChart, ChartFrame, Legend, LineChart, ServerChart, StatTile, seriesColor,
} from '../components/charts'
import {
  Badge, ErrorBanner, ProvenanceBadge, SeverityBadge, StateBadge, Table, Tabs,
  money,
} from '../components/ui'
import { ApiError } from '../lib/api'
import { I18nProvider, useI18n, useT } from '../i18n'
import type { ChartResponse } from '../types'

const CHART: ChartResponse = {
  chart: 'planned_vs_actual',
  title: 'Planned versus actual effort',
  unit: 'person_hours',
  asOf: '2026-10-01T08:00:00Z',
  dataFreshness: 'live query at request time',
  definition: 'Planned is the current detailed estimate rollup.',
  categories: ['baseline', 'planned', 'actual', 'remaining'],
  series: [{
    key: 'effort', label: 'Effort',
    points: [
      { category: 'baseline', value: 0 },
      { category: 'planned', value: 124 },
      { category: 'actual', value: 40 },
      { category: 'remaining', value: 84 },
    ],
  }],
  warnings: ['3 unapproved time entries are excluded from actual.'],
  insufficientData: false,
  filters: {},
}

describe('chart primitives', () => {
  it('assigns categorical colours in fixed order and never cycles', () => {
    expect(seriesColor(0)).toBe('var(--series-1)')
    expect(seriesColor(4)).toBe('var(--series-5)')
    // Past the fixed slots a series is folded rather than given a new hue.
    expect(seriesColor(5)).toBe('var(--text-muted)')
    expect(seriesColor(9)).toBe('var(--text-muted)')
  })

  it('renders the definition, unit, as-of time and warnings', () => {
    render(<ServerChart data={CHART} kind="bar" />)
    expect(screen.getByText(CHART.title)).toBeInTheDocument()
    expect(screen.getByText('person_hours')).toBeInTheDocument()
    expect(screen.getByText(/Planned is the current detailed estimate rollup/))
      .toBeInTheDocument()
    expect(screen.getByText(/unapproved time entries/)).toBeInTheDocument()
    expect(screen.getByText(/live query at request time/)).toBeInTheDocument()
  })

  it('offers a values table so the chart never depends on colour alone', async () => {
    render(<ServerChart data={CHART} kind="bar" />)
    await userEvent.click(screen.getByRole('button', { name: 'Show values' }))

    const table = screen.getByRole('table')
    expect(table).toBeInTheDocument()
    expect(screen.getByText('124')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show chart' }))
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('states when there is not enough data instead of drawing an empty plot', () => {
    render(<ServerChart data={{ ...CHART, insufficientData: true }} kind="bar" />)
    expect(screen.getByText(/Not enough data yet/)).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('shows a legend only when two or more series are plotted', () => {
    const { rerender, container } = render(
      <Legend items={[{ label: 'Effort', color: 'var(--series-1)' }]} />)
    expect(container.querySelector('ul')).toBeNull()

    rerender(<Legend items={[{ label: 'Planned', color: 'var(--series-1)' },
                             { label: 'Actual', color: 'var(--series-2)' }]} />)
    expect(screen.getByText('Planned')).toBeInTheDocument()
    expect(screen.getByText('Actual')).toBeInTheDocument()
  })

  it('draws bars with a rounded data end and capped thickness', () => {
    const { container } = render(
      <BarChart categories={['a', 'b']} series={CHART.series} unit="h" />)
    const bars = container.querySelectorAll('rect')
    expect(bars.length).toBeGreaterThan(0)
    bars.forEach((bar) => {
      expect(bar.getAttribute('rx')).toBe('4')
      expect(Number(bar.getAttribute('width'))).toBeLessThanOrEqual(24)
    })
  })

  it('draws 2px lines with markers that carry a surface ring', () => {
    const { container } = render(
      <LineChart series={[{ key: 's', label: 'Remaining',
                            points: [{ x: '2026-03-02', value: 10 },
                                     { x: '2026-03-03', value: 6 }] }]} />)
    const path = container.querySelector('path[stroke]')
    expect(path?.getAttribute('stroke-width')).toBe('2')
    const marker = container.querySelector('circle')
    expect(marker?.getAttribute('r')).toBe('4')
    expect(marker?.getAttribute('stroke')).toBe('var(--surface-1)')
    expect(marker?.getAttribute('stroke-width')).toBe('2')
  })

  it('labels a stat tile with its value and hint', () => {
    render(<StatTile label="Pending approvals" value={7} hint="Needing renewal"
                     tone="warning" />)
    expect(screen.getByText('Pending approvals')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('Needing renewal')).toBeInTheDocument()
  })

  it('keeps the frame usable without a table', () => {
    render(<ChartFrame title="Bare"><p>content</p></ChartFrame>)
    expect(screen.queryByRole('button', { name: 'Show values' })).not.toBeInTheDocument()
    expect(screen.getByText('content')).toBeInTheDocument()
  })
})

describe('interface primitives', () => {
  it('renders artifact state with an icon as well as colour', () => {
    render(<><StateBadge state="approved" /><StateBadge state="draft" /></>)
    expect(screen.getByText('approved')).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()
    expect(screen.getByText('✓')).toBeInTheDocument()
  })

  it('distinguishes evidence, assumptions and AI proposals', () => {
    const { rerender } = render(<ProvenanceBadge provenance="evidence" />)
    expect(screen.getByText('evidence backed')).toBeInTheDocument()

    rerender(<ProvenanceBadge provenance="ai_suggestion" />)
    expect(screen.getByText('AI proposal')).toBeInTheDocument()

    rerender(<ProvenanceBadge provenance="assumption" />)
    expect(screen.getByText('analyst assumption')).toBeInTheDocument()
  })

  it('shows severity with an icon', () => {
    render(<SeverityBadge severity="critical" />)
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('⛔')).toBeInTheDocument()
  })

  it('surfaces the server error code and details', async () => {
    const error = new ApiError(409, 'version_conflict', 'An item changed',
                               { refreshedHash: 'abc' })
    const onRetry = () => {}
    render(<ErrorBanner error={error} onRetry={onRetry} />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('An item changed')).toBeInTheDocument()
    expect(screen.getByText('Code: version_conflict')).toBeInTheDocument()
    expect(screen.getByText(/refreshedHash/)).toBeInTheDocument()
  })

  it('renders an empty table message rather than an empty grid', () => {
    render(<Table rows={[]} rowKey={(row: { id: string }) => row.id}
                  columns={[{ key: 'a', header: 'A', render: () => null }]}
                  empty="Nothing to show yet" />)
    expect(screen.getByText('Nothing to show yet')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('marks the selected tab for assistive technology', () => {
    const tabs = [{ key: 'a', label: 'Alpha' }, { key: 'b', label: 'Beta', count: 3 }]
    render(<Tabs tabs={tabs} active="b" onChange={() => {}} />)
    expect(screen.getByRole('tab', { name: /Beta/ })).toHaveAttribute('aria-selected',
                                                                     'true')
    expect(screen.getByRole('tab', { name: 'Alpha' })).toHaveAttribute('aria-selected',
                                                                      'false')
  })

  it('formats money with its currency and an em dash when absent', () => {
    expect(money({ amount: '1540.00', currency: 'EUR' })).toContain('EUR')
    expect(money(null)).toBe('—')
  })

  it('renders a badge with a neutral tone for an unknown value', () => {
    render(<Badge tone="not-a-tone">unknown</Badge>)
    expect(screen.getByText('unknown')).toBeInTheDocument()
  })
})

function Greeting() {
  const { t, setLocale } = useI18n()
  return (
    <div>
      <p>{t('navApprovals')}</p>
      <button type="button" onClick={() => setLocale('el')}>Greek</button>
    </div>
  )
}

function UnknownKey() {
  const t = useT()
  return <p>{t('notATranslationKey' as never)}</p>
}

describe('internationalisation', () => {
  it('renders English by default', () => {
    render(<I18nProvider><Greeting /></I18nProvider>)
    expect(screen.getByText('Approval inbox')).toBeInTheDocument()
  })

  it('honours the stored locale', () => {
    localStorage.setItem('ait.locale', 'el')
    render(<I18nProvider><Greeting /></I18nProvider>)
    expect(screen.getByText('Εγκρίσεις')).toBeInTheDocument()
  })

  it('switches language without a reload and remembers the choice', async () => {
    render(<I18nProvider><Greeting /></I18nProvider>)
    await userEvent.click(screen.getByRole('button', { name: 'Greek' }))

    expect(screen.getByText('Εγκρίσεις')).toBeInTheDocument()
    expect(localStorage.getItem('ait.locale')).toBe('el')
    expect(document.documentElement.lang).toBe('el')
  })

  it('returns the key itself when no translation exists', () => {
    render(<I18nProvider><UnknownKey /></I18nProvider>)
    expect(screen.getByText('notATranslationKey')).toBeInTheDocument()
  })
})
