/**
 * SVG chart primitives.
 *
 * Rules applied throughout (see the project's visualization guidance):
 * one y axis per chart, categorical hues assigned in fixed order and never
 * cycled, 2px lines with >=8px markers carrying a 2px surface ring, bars capped
 * at 24px with a 4px rounded data end, a 2px surface gap between stacked
 * segments, hairline recessive gridlines, a legend whenever two or more series
 * are plotted, selective direct labels, a hover layer, and a values table so the
 * chart never depends on colour alone.
 */
import { useId, useMemo, useState } from 'react'
import type { ChartResponse, ChartSeries } from '../types'

const SERIES_VARS = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
  'var(--series-5)',
]

export function seriesColor(index: number) {
  // Past the fixed slots a series folds into "Other" rather than inventing a hue.
  return SERIES_VARS[index] ?? 'var(--text-muted)'
}

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0]
  const rough = max / count
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? magnitude * 10
  const ticks: number[] = []
  for (let value = 0; value <= max + step * 0.001; value += step) ticks.push(Number(value.toFixed(6)))
  return ticks
}

export function formatNumber(value: number, unit?: string) {
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 100) / 100
  const text = rounded.toLocaleString(undefined, { maximumFractionDigits: 2 })
  return unit ? `${text} ${unit}` : text
}

interface ChartFrameProps {
  title: string
  unit?: string
  asOf?: string
  definition?: string
  freshness?: string
  warnings?: string[]
  insufficient?: boolean
  children: React.ReactNode
  table?: { columns: string[]; rows: (string | number)[][] }
  actions?: React.ReactNode
}

/** Shared chart container: title, units, as-of time, definition and table view. */
export function ChartFrame({
  title, unit, asOf, definition, freshness, warnings = [], insufficient,
  children, table, actions,
}: ChartFrameProps) {
  const [showTable, setShowTable] = useState(false)
  return (
    <section className="viz-root card card-pad">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
          <p className="text-xs text-ink-500">
            {unit ? <span className="font-medium">{unit}</span> : null}
            {asOf ? <span> · as of {new Date(asOf).toLocaleString()}</span> : null}
            {freshness ? <span> · {freshness}</span> : null}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {table ? (
            <button type="button" className="btn-ghost text-xs" aria-pressed={showTable}
                    onClick={() => setShowTable((value) => !value)}>
              {showTable ? 'Show chart' : 'Show values'}
            </button>
          ) : null}
        </div>
      </header>

      {insufficient ? (
        <p className="rounded-lg bg-ink-100 px-3 py-6 text-center text-sm text-ink-600">
          Not enough data yet. The chart appears once the underlying records exist.
        </p>
      ) : showTable && table ? (
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-ink-200">
                {table.columns.map((column) => <th key={column} className="th">{column}</th>)}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, index) => (
                <tr key={index} className="border-b border-ink-100 last:border-0">
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="td tabular-nums">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}

      {definition ? (
        <p className="mt-3 border-t border-ink-100 pt-2 text-xs leading-relaxed text-ink-500">
          <span className="font-medium text-ink-600">Definition. </span>{definition}
        </p>
      ) : null}
      {warnings.length ? (
        <ul className="mt-2 space-y-1">
          {warnings.map((warning) => (
            <li key={warning} className="text-xs text-amber-700">· {warning}</li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  if (items.length < 2) return null
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-xs text-ink-600">
          <span className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ background: item.color }} aria-hidden />
          {item.label}
        </li>
      ))}
    </ul>
  )
}

interface Tooltip {
  x: number
  y: number
  lines: string[]
}

/** Grouped column chart. One axis, bars capped at 24px with a rounded cap. */
export function BarChart({
  categories, series, unit, height = 220, highlightIndex,
}: {
  categories: string[]
  series: ChartSeries[]
  unit?: string
  height?: number
  highlightIndex?: number
}) {
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const padding = { top: 16, right: 16, bottom: 34, left: 52 }
  const width = 640
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom

  const values = series.flatMap((s) => s.points.map((p) => Number(p.value) || 0))
  const max = Math.max(...values, 1)
  const ticks = niceTicks(max)
  const scaleMax = ticks[ticks.length - 1] || 1
  const bandWidth = plotWidth / Math.max(categories.length, 1)
  const barWidth = Math.min(24, (bandWidth - 12) / Math.max(series.length, 1))

  return (
    <div className="relative">
      <Legend items={series.map((s, index) => ({ label: s.label, color: seriesColor(index) }))} />
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img"
           aria-label={`Bar chart${unit ? ` in ${unit}` : ''}`}>
        {ticks.map((tick) => {
          const y = padding.top + plotHeight - (tick / scaleMax) * plotHeight
          return (
            <g key={tick}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y}
                    stroke="var(--grid)" strokeWidth={1} />
              <text x={padding.left - 8} y={y + 4} textAnchor="end"
                    className="fill-ink-500" fontSize={11}>
                {tick.toLocaleString()}
              </text>
            </g>
          )
        })}

        {categories.map((category, categoryIndex) => {
          const bandStart = padding.left + categoryIndex * bandWidth
          const groupWidth = barWidth * series.length + 2 * (series.length - 1)
          const groupStart = bandStart + (bandWidth - groupWidth) / 2
          return (
            <g key={category}>
              {series.map((s, seriesIndex) => {
                const point = s.points.find((p) => (p.category ?? p.x) === category)
                const value = Number(point?.value ?? 0)
                const barHeight = Math.max((value / scaleMax) * plotHeight, value > 0 ? 2 : 0)
                const x = groupStart + seriesIndex * (barWidth + 2)
                const y = padding.top + plotHeight - barHeight
                const dimmed = highlightIndex !== undefined && highlightIndex !== seriesIndex
                return (
                  <rect
                    key={s.key}
                    x={x}
                    y={y}
                    width={barWidth}
                    height={barHeight}
                    rx={4}
                    fill={dimmed ? 'var(--grid)' : seriesColor(seriesIndex)}
                    onMouseEnter={() =>
                      setTooltip({
                        x: x + barWidth / 2,
                        y,
                        lines: [category, `${s.label}: ${formatNumber(value, unit)}`],
                      })}
                    onMouseLeave={() => setTooltip(null)}
                  />
                )
              })}
              <text x={bandStart + bandWidth / 2} y={height - 12} textAnchor="middle"
                    className="fill-ink-500" fontSize={11}>
                {category.length > 14 ? `${category.slice(0, 13)}…` : category}
              </text>
            </g>
          )
        })}

        {/* Direct labels for a single series, where they always fit. */}
        {series.length === 1
          ? categories.map((category, categoryIndex) => {
              const point = series[0].points.find((p) => (p.category ?? p.x) === category)
              const value = Number(point?.value ?? 0)
              if (!value) return null
              const barHeight = (value / scaleMax) * plotHeight
              return (
                <text key={`label-${category}`}
                      x={padding.left + categoryIndex * bandWidth + bandWidth / 2}
                      y={padding.top + plotHeight - barHeight - 6}
                      textAnchor="middle" fontSize={11} className="fill-ink-700">
                  {formatNumber(value)}
                </text>
              )
            })
          : null}

        <line x1={padding.left} x2={width - padding.right}
              y1={padding.top + plotHeight} y2={padding.top + plotHeight}
              stroke="var(--grid)" strokeWidth={1} />
      </svg>
      {tooltip ? <TooltipBox tooltip={tooltip} width={width} /> : null}
    </div>
  )
}

/** Line chart with optional area wash. Used for burndown and trends. */
export function LineChart({
  series, unit, height = 240, areas = false,
}: {
  series: ChartSeries[]
  unit?: string
  height?: number
  areas?: boolean
}) {
  const clipId = useId()
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const padding = { top: 16, right: 56, bottom: 34, left: 52 }
  const width = 640
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom

  const labels = useMemo(() => {
    const seen: string[] = []
    for (const s of series) {
      for (const point of s.points) {
        const key = String(point.x ?? point.category ?? '')
        if (!seen.includes(key)) seen.push(key)
      }
    }
    return seen
  }, [series])

  const values = series.flatMap((s) => s.points.map((p) => Number(p.value) || 0))
  const max = Math.max(...values, 1)
  const ticks = niceTicks(max)
  const scaleMax = ticks[ticks.length - 1] || 1
  const stepX = labels.length > 1 ? plotWidth / (labels.length - 1) : plotWidth

  const pointAt = (s: ChartSeries, label: string) =>
    s.points.find((p) => String(p.x ?? p.category ?? '') === label)

  return (
    <div className="relative">
      <Legend items={series.map((s, index) => ({ label: s.label, color: seriesColor(index) }))} />
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img"
           aria-label={`Line chart${unit ? ` in ${unit}` : ''}`}>
        <defs>
          <clipPath id={clipId}>
            <rect x={padding.left} y={padding.top} width={plotWidth} height={plotHeight} />
          </clipPath>
        </defs>

        {ticks.map((tick) => {
          const y = padding.top + plotHeight - (tick / scaleMax) * plotHeight
          return (
            <g key={tick}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y}
                    stroke="var(--grid)" strokeWidth={1} />
              <text x={padding.left - 8} y={y + 4} textAnchor="end" fontSize={11}
                    className="fill-ink-500">{tick.toLocaleString()}</text>
            </g>
          )
        })}

        {series.map((s, seriesIndex) => {
          const coords = labels
            .map((label, index) => {
              const point = pointAt(s, label)
              if (!point) return null
              const value = Number(point.value) || 0
              return {
                x: padding.left + index * stepX,
                y: padding.top + plotHeight - (value / scaleMax) * plotHeight,
                value,
                label,
              }
            })
            .filter(Boolean) as { x: number; y: number; value: number; label: string }[]
          if (!coords.length) return null
          const path = coords.map((c, index) => `${index === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ')
          const last = coords[coords.length - 1]
          return (
            <g key={s.key} clipPath={areas ? `url(#${clipId})` : undefined}>
              {areas ? (
                <path
                  d={`${path} L${last.x},${padding.top + plotHeight} L${coords[0].x},${padding.top + plotHeight} Z`}
                  fill={seriesColor(seriesIndex)} fillOpacity={0.1} />
              ) : null}
              <path d={path} fill="none" stroke={seriesColor(seriesIndex)} strokeWidth={2}
                    strokeLinecap="round" strokeLinejoin="round" />
              {coords.map((c) => (
                <circle key={`${s.key}-${c.label}`} cx={c.x} cy={c.y} r={4}
                        fill={seriesColor(seriesIndex)} stroke="var(--surface-1)"
                        strokeWidth={2}
                        onMouseEnter={() =>
                          setTooltip({
                            x: c.x, y: c.y,
                            lines: [c.label, `${s.label}: ${formatNumber(c.value, unit)}`],
                          })}
                        onMouseLeave={() => setTooltip(null)} />
              ))}
              {/* One direct label at the series end, never a number on every point. */}
              <text x={last.x + 8} y={last.y + 4} fontSize={11} className="fill-ink-700">
                {formatNumber(last.value)}
              </text>
            </g>
          )
        })}

        {labels.map((label, index) => {
          if (labels.length > 10 && index % Math.ceil(labels.length / 8) !== 0) return null
          return (
            <text key={label} x={padding.left + index * stepX} y={height - 12}
                  textAnchor="middle" fontSize={11} className="fill-ink-500">
              {label.length > 10 ? label.slice(5) : label}
            </text>
          )
        })}
        <line x1={padding.left} x2={width - padding.right}
              y1={padding.top + plotHeight} y2={padding.top + plotHeight}
              stroke="var(--grid)" strokeWidth={1} />
      </svg>
      {tooltip ? <TooltipBox tooltip={tooltip} width={width} /> : null}
    </div>
  )
}

/** Stacked area, used for the Kanban cumulative flow diagram. */
export function StackedAreaChart({
  series, unit, height = 260,
}: {
  series: ChartSeries[]
  unit?: string
  height?: number
}) {
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const padding = { top: 16, right: 16, bottom: 34, left: 52 }
  const width = 640
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom

  const labels = series[0]?.points.map((p) => String(p.x ?? '')) ?? []
  const totals = labels.map((_, index) =>
    series.reduce((sum, s) => sum + (Number(s.points[index]?.value) || 0), 0))
  const max = Math.max(...totals, 1)
  const ticks = niceTicks(max)
  const scaleMax = ticks[ticks.length - 1] || 1
  const stepX = labels.length > 1 ? plotWidth / (labels.length - 1) : plotWidth

  const stacked = labels.map((_, index) => {
    let cumulative = 0
    return series.map((s) => {
      const value = Number(s.points[index]?.value) || 0
      const base = cumulative
      cumulative += value
      return { base, top: cumulative, value }
    })
  })

  return (
    <div className="relative">
      <Legend items={series.map((s, index) => ({ label: s.label, color: seriesColor(index) }))} />
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img"
           aria-label={`Cumulative flow${unit ? ` in ${unit}` : ''}`}>
        {ticks.map((tick) => {
          const y = padding.top + plotHeight - (tick / scaleMax) * plotHeight
          return (
            <g key={tick}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y}
                    stroke="var(--grid)" strokeWidth={1} />
              <text x={padding.left - 8} y={y + 4} textAnchor="end" fontSize={11}
                    className="fill-ink-500">{tick.toLocaleString()}</text>
            </g>
          )
        })}

        {series.map((s, seriesIndex) => {
          const top = labels.map((_, index) => ({
            x: padding.left + index * stepX,
            y: padding.top + plotHeight - (stacked[index][seriesIndex].top / scaleMax) * plotHeight,
          }))
          const base = labels.map((_, index) => ({
            x: padding.left + index * stepX,
            y: padding.top + plotHeight - (stacked[index][seriesIndex].base / scaleMax) * plotHeight,
          })).reverse()
          const path = [...top.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`),
                        ...base.map((c) => `L${c.x},${c.y}`), 'Z'].join(' ')
          return (
            <g key={s.key}>
              {/* A 2px surface stroke keeps touching bands separated. */}
              <path d={path} fill={seriesColor(seriesIndex)} fillOpacity={0.85}
                    stroke="var(--surface-1)" strokeWidth={2}
                    onMouseEnter={() => {
                      const lastIndex = labels.length - 1
                      setTooltip({
                        x: padding.left + lastIndex * stepX,
                        y: top[lastIndex]?.y ?? padding.top,
                        lines: [s.label,
                                `${formatNumber(stacked[lastIndex][seriesIndex].value, unit)}`],
                      })
                    }}
                    onMouseLeave={() => setTooltip(null)} />
            </g>
          )
        })}

        {labels.map((label, index) => {
          if (index % Math.max(Math.ceil(labels.length / 7), 1) !== 0) return null
          return (
            <text key={label} x={padding.left + index * stepX} y={height - 12}
                  textAnchor="middle" fontSize={11} className="fill-ink-500">
              {label.slice(5)}
            </text>
          )
        })}
      </svg>
      {tooltip ? <TooltipBox tooltip={tooltip} width={width} /> : null}
    </div>
  )
}

function TooltipBox({ tooltip, width }: { tooltip: Tooltip; width: number }) {
  const left = `${(tooltip.x / width) * 100}%`
  return (
    <div
      className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-lg border
                 border-ink-200 bg-surface px-2 py-1 text-xs shadow-md"
      style={{ left, top: Math.max(tooltip.y - 8, 0) }}
    >
      {tooltip.lines.map((line, index) => (
        <div key={index} className={index === 0 ? 'font-medium text-ink-900' : 'text-ink-600'}>
          {line}
        </div>
      ))}
    </div>
  )
}

/** A single headline number. The form of choice when the story is one value. */
export function StatTile({
  label, value, unit, hint, tone = 'neutral',
}: {
  label: string
  value: string | number
  unit?: string
  hint?: string
  tone?: 'neutral' | 'good' | 'warning' | 'critical'
}) {
  const toneClass = {
    neutral: 'text-ink-900',
    good: 'text-emerald-700',
    warning: 'text-amber-700',
    critical: 'text-red-700',
  }[tone]
  return (
    <div className="card card-pad">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${toneClass}`}>
        {typeof value === 'number' ? value.toLocaleString() : value}
        {unit ? <span className="ml-1 text-sm font-normal text-ink-500">{unit}</span> : null}
      </p>
      {hint ? <p className="mt-1 text-xs text-ink-500">{hint}</p> : null}
    </div>
  )
}

/** Renders a backend ChartResponse with its definition, units and freshness. */
export function ServerChart({
  data, kind = 'bar',
}: {
  data: ChartResponse
  kind?: 'bar' | 'line' | 'area' | 'stacked'
}) {
  const categories = data.categories.length
    ? data.categories
    : Array.from(new Set(data.series.flatMap((s) =>
        s.points.map((p) => String(p.category ?? p.x ?? '')))))

  const table = {
    columns: ['', ...data.series.map((s) => s.label)],
    rows: categories.map((category) => [
      category,
      ...data.series.map((s) => {
        const point = s.points.find((p) => (p.category ?? p.x) === category)
        return point ? String(point.value) : '—'
      }),
    ]),
  }

  return (
    <ChartFrame
      title={data.title}
      unit={data.unit}
      asOf={data.asOf}
      freshness={data.dataFreshness}
      definition={data.definition}
      warnings={data.warnings}
      insufficient={data.insufficientData}
      table={table}
    >
      {kind === 'line' ? (
        <LineChart series={data.series} unit={data.unit} />
      ) : kind === 'area' ? (
        <LineChart series={data.series} unit={data.unit} areas />
      ) : kind === 'stacked' ? (
        <StackedAreaChart series={data.series} unit={data.unit} />
      ) : (
        <BarChart categories={categories} series={data.series} unit={data.unit} />
      )}
    </ChartFrame>
  )
}
