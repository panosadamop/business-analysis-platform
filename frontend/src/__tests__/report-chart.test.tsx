/** Charting a report: the aggregation and the chart surface. */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  DEFAULT_CHART_SETTINGS, ReportChart, ReportChartControls, aggregateRows,
} from '../components/report-chart'
import type { ChartSettings } from '../components/report-chart'
import type { ReportPreview } from '../types'

const ROWS = [
  { stableId: 'STORY-001', type: 'story', effortHours: 8, priority: 'high' },
  { stableId: 'STORY-002', type: 'story', effortHours: 13, priority: 'high' },
  { stableId: 'FEAT-001', type: 'feature', effortHours: 4, priority: 'medium' },
  { stableId: 'EPIC-001', type: 'epic', effortHours: 0, priority: 'medium' },
]

const PREVIEW: ReportPreview = {
  dataset: 'backlog',
  columns: [
    { key: 'stableId', label: 'ID', type: 'string', clientSafe: true },
    { key: 'type', label: 'Type', type: 'string', clientSafe: true },
    { key: 'effortHours', label: 'Effort (person hours)', type: 'number', clientSafe: true },
    { key: 'priority', label: 'Priority', type: 'string', clientSafe: true },
  ],
  rows: ROWS,
  totalRows: ROWS.length,
  truncated: false,
  snapshotId: 'snap-abc123',
  generatedAt: '2026-10-01T08:00:00Z',
  appliedPermissions: ['report.read'],
  warnings: [],
  totals: { effortHours: 25 },
}

function settings(overrides: Partial<ChartSettings> = {}): ChartSettings {
  return { ...DEFAULT_CHART_SETTINGS, chartType: 'bar', groupBy: 'type',
           measure: 'effortHours', ...overrides }
}

describe('report aggregation', () => {
  it('sums a measure per category', () => {
    const { categories, series } = aggregateRows(ROWS, settings())
    expect(categories).toEqual(['story', 'feature', 'epic'])
    expect(series).toHaveLength(1)
    const points = Object.fromEntries(
      series[0].points.map((point) => [point.category, point.value]))
    expect(points).toEqual({ story: 21, feature: 4, epic: 0 })
  })

  it('counts rows without needing a measure', () => {
    const { series } = aggregateRows(ROWS, settings({ aggregation: 'count', measure: '' }))
    const points = Object.fromEntries(
      series[0].points.map((point) => [point.category, point.value]))
    expect(points).toEqual({ story: 2, feature: 1, epic: 1 })
  })

  it('averages, and takes the minimum and maximum', () => {
    const average = aggregateRows(ROWS, settings({ aggregation: 'average' }))
    expect(average.series[0].points.find((p) => p.category === 'story')?.value).toBe(10.5)

    const minimum = aggregateRows(ROWS, settings({ aggregation: 'min' }))
    expect(minimum.series[0].points.find((p) => p.category === 'story')?.value).toBe(8)

    const maximum = aggregateRows(ROWS, settings({ aggregation: 'max' }))
    expect(maximum.series[0].points.find((p) => p.category === 'story')?.value).toBe(13)
  })

  it('splits into one series per value of a second dimension', () => {
    const { categories, series } = aggregateRows(ROWS, settings({ seriesBy: 'priority' }))
    expect(categories).toEqual(['story', 'feature', 'epic'])
    expect(series.map((item) => item.label).sort()).toEqual(['high', 'medium'])
  })

  it('treats a missing value as its own category rather than dropping the row', () => {
    const rows = [...ROWS, { stableId: 'X', type: null, effortHours: 5 }]
    const { categories } = aggregateRows(rows, settings())
    expect(categories).toContain('Not set')
  })

  it('folds a long tail of series into Other instead of inventing hues', () => {
    const rows = Array.from({ length: 9 }, (_, index) => ({
      type: 'story', owner: `person-${index}`, effortHours: index + 1,
    }))
    const { series } = aggregateRows(rows, settings({ seriesBy: 'owner' }))
    expect(series).toHaveLength(6)
    expect(series[5].label).toBe('Other')
    // 6 + 7 + 8 + 9 = the four folded owners.
    expect(series[5].points[0].value).toBe(30)
  })

  it('returns nothing to plot when no grouping column is chosen', () => {
    expect(aggregateRows(ROWS, settings({ groupBy: '' })))
      .toEqual({ categories: [], series: [] })
  })

  it('ignores values that are not numeric', () => {
    const rows = [{ type: 'story', effortHours: 'not a number' },
                  { type: 'story', effortHours: '7' }]
    const { series } = aggregateRows(rows, settings())
    expect(series[0].points[0].value).toBe(7)
  })
})

describe('report chart surface', () => {
  it('asks for a grouping before it plots anything', () => {
    render(<ReportChart preview={PREVIEW} settings={settings({ groupBy: '' })} />)
    expect(screen.getByText(/Choose a column to group by/)).toBeInTheDocument()
  })

  it('says so when the measure has no numeric values', () => {
    const preview = { ...PREVIEW, rows: [{ type: 'story', effortHours: null }] }
    render(<ReportChart preview={preview} settings={settings()} />)
    expect(screen.getByText(/nothing to plot/)).toBeInTheDocument()
  })

  it('states its definition, snapshot and the rows it covers', () => {
    render(<ReportChart preview={PREVIEW} settings={settings()} />)
    expect(screen.getByText('Effort (person hours) by Type')).toBeInTheDocument()
    expect(screen.getByText(/snapshot snap-abc123/)).toBeInTheDocument()
    expect(screen.getByText(/sum of Effort \(person hours\) per Type/)).toBeInTheDocument()
    expect(screen.getByText(/after the server applied your permissions/))
      .toBeInTheDocument()
  })

  it('offers the same values as a table beside the plot', async () => {
    render(<ReportChart preview={PREVIEW} settings={settings()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Show values' }))

    const table = screen.getByRole('table')
    expect(table).toBeInTheDocument()
    expect(screen.getByText('21')).toBeInTheDocument()
  })

  it('renders a line chart when that view is chosen', () => {
    const { container } = render(
      <ReportChart preview={PREVIEW} settings={settings({ chartType: 'line' })} />)
    const path = container.querySelector('path[stroke]')
    expect(path?.getAttribute('stroke-width')).toBe('2')
  })
})

describe('report chart controls', () => {
  it('offers only numeric columns as the measure', () => {
    render(<ReportChartControls columns={PREVIEW.columns} settings={settings()}
                                onChange={() => {}} />)
    const measure = screen.getByLabelText('Measure') as HTMLSelectElement
    const options = Array.from(measure.options).map((option) => option.textContent)
    expect(options).toContain('Effort (person hours)')
    expect(options).not.toContain('Type')
  })

  it('disables the measure when counting rows', () => {
    render(<ReportChartControls columns={PREVIEW.columns}
                                settings={settings({ aggregation: 'count' })}
                                onChange={() => {}} />)
    expect(screen.getByLabelText('Measure')).toBeDisabled()
  })

  it('reports a change of view to the caller', async () => {
    const onChange = vi.fn()
    render(<ReportChartControls columns={PREVIEW.columns} settings={settings()}
                                onChange={onChange} />)
    await userEvent.selectOptions(screen.getByLabelText('View'), 'line')
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ chartType: 'line' }))
  })

  it('does not offer the grouping column as the split dimension', () => {
    render(<ReportChartControls columns={PREVIEW.columns}
                                settings={settings({ groupBy: 'type' })}
                                onChange={() => {}} />)
    const split = screen.getByLabelText(/Split by/) as HTMLSelectElement
    const options = Array.from(split.options).map((option) => option.textContent)
    expect(options).not.toContain('Type')
    expect(options).toContain('Priority')
  })
})
