import { useMemo } from 'react'

const DAY = 86400000
const ROW = 28
const HEAD = 28
const LABEL_W = 0

function d(iso) { return new Date(iso + 'T00:00:00') }
function addDays(date, n) { return new Date(date.getTime() + n * DAY) }
function diffDays(a, b) { return Math.round((b - a) / DAY) }

/**
 * rows: activities from the API (in outline order). pxPerDay: zoom.
 * Bars are laid out on calendar days (not working-day indices) so weekends
 * show as gaps, exactly as the original UI did.
 */
export default function Gantt({ rows, holidays = [], selectedId, onSelect, pxPerDay = 12, projectStart }) {
  const layout = useMemo(() => {
    if (!rows.length) return null
    let min = d(projectStart || rows[0].plannedStart)
    let max = d(rows[0].plannedFinish)
    for (const r of rows) {
      const s = d(r.plannedStart), f = d(r.plannedFinish)
      if (s < min) min = s
      if (f > max) max = f
      if (r.actualStart && d(r.actualStart) < min) min = d(r.actualStart)
      if (r.actualFinish && d(r.actualFinish) > max) max = d(r.actualFinish)
      if (r.targetDate && d(r.targetDate) > max) max = d(r.targetDate)
    }
    min = addDays(min, -2)
    max = addDays(max, 6)
    const days = diffDays(min, max) + 1
    const x = (date) => diffDays(min, d(date)) * pxPerDay
    const xEnd = (date) => (diffDays(min, d(date)) + 1) * pxPerDay
    const width = days * pxPerDay + 220
    return { min, max, days, x, xEnd, width }
  }, [rows, pxPerDay, projectStart])

  if (!layout) return <div className="blank">Nothing to draw yet.</div>
  const { min, days, x, xEnd, width } = layout
  const hol = new Set(holidays)

  // header ticks: months when zoomed out, weeks when zoomed in
  const ticks = []
  const monthly = pxPerDay < 8
  for (let i = 0; i < days; i++) {
    const day = addDays(min, i)
    const isTick = monthly ? day.getDate() === 1 : day.getDay() === 1
    if (isTick || i === 0) {
      ticks.push({ left: i * pxPerDay, label: monthly
        ? day.toLocaleDateString(undefined, { month: 'short', year: '2-digit' })
        : day.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) })
    }
  }

  // shaded non-working days
  const shade = []
  for (let i = 0; i < days; i++) {
    const day = addDays(min, i)
    const iso = day.toISOString().slice(0, 10)
    if (day.getDay() === 0 || day.getDay() === 6 || hol.has(iso)) shade.push(i)
  }
  const todayIdx = diffDays(min, d(new Date().toISOString().slice(0, 10)))

  // dependency arrows: from predecessor bar end to successor bar start
  const index = new Map(rows.map((r, i) => [r.id, i]))
  const arrows = []
  rows.forEach((r, i) => {
    for (const dep of r.dependencies || []) {
      const pi = index.get(dep.predecessorId)
      if (pi === undefined) continue
      const p = rows[pi]
      const fromStart = dep.type === 1 || dep.type === 3 // SS, SF leave from predecessor start
      const toStart = dep.type === 0 || dep.type === 1   // FS, SS arrive at successor start
      const x1 = fromStart ? x(p.plannedStart) : xEnd(p.plannedFinish)
      const y1 = HEAD + pi * ROW + ROW / 2
      const x2 = toStart ? x(r.plannedStart) : xEnd(r.plannedFinish)
      const y2 = HEAD + i * ROW + ROW / 2
      const mid = toStart ? Math.max(x1 + 8, x2 - 8) : Math.min(x1 - 8, x2 + 8)
      arrows.push({ key: `${p.id}-${r.id}`, path: `M${x1},${y1} H${mid} V${y2} H${x2}`, x2, y2, toStart, crit: r.isCritical && p.isCritical })
    }
  })

  return (
    <div className="gantt" style={{ width, minHeight: HEAD + rows.length * ROW }}>
      <div className="head" style={{ width }}>
        {ticks.map((t, i) => <span key={i} style={{ left: t.left }}>{t.label}</span>)}
      </div>
      <div className="rows" style={{ width }}>
        {rows.map((r, i) => {
          const left = x(r.plannedStart)
          const w = Math.max(pxPerDay, xEnd(r.plannedFinish) - left)
          const isMilestoneMarker = r.level === 0 && !r.isSummary && r.duration === 0
          return (
            <div key={r.id} className={'row' + (r.id === selectedId ? ' sel' : '')} onClick={() => onSelect?.(r.id)}>
              {i === 0 && shade.map((s) => <div key={s} className="weekend" style={{ left: s * pxPerDay, width: pxPerDay, height: rows.length * ROW }} />)}
              {i === 0 && todayIdx >= 0 && todayIdx < days && <div className="today" style={{ left: todayIdx * pxPerDay + pxPerDay / 2, height: rows.length * ROW }} title="Today" />}
              {r.baselineStart !== null && r.baselineStart !== undefined && r.plannedStart && (
                <div className="base" style={{ left, width: w }} title="Baseline" />
              )}
              {r.actualStart && (
                <div className="actual" style={{ left: x(r.actualStart), width: Math.max(4, xEnd(r.actualFinish || r.actualStart) - x(r.actualStart)) }} title="Actual" />
              )}
              {isMilestoneMarker ? (
                <div className="dia" style={{ left: left + pxPerDay / 2 - 6 }} title={r.name} />
              ) : r.isSummary ? (
                <div className="sum" style={{ left, width: w }} title={r.name} />
              ) : (
                <div className={'bar' + (r.isCritical ? ' crit' : '') + (r.mode === 1 ? ' manual' : '')} style={{ left, width: w }} title={`${r.name}: ${r.plannedStart} → ${r.plannedFinish}`}>
                  {r.percentComplete > 0 && <div className="prog" style={{ width: `${Math.min(100, r.percentComplete)}%` }} />}
                </div>
              )}
              {r.targetDate && r.level === 0 && (
                <div className="dia" style={{ left: x(r.targetDate) + pxPerDay / 2 - 6, background: 'transparent', border: '2px solid var(--warn)', width: 10, height: 10 }} title={`Target ${r.targetDate}`} />
              )}
              <span className="lbl" style={{ left: left + w + 8 }}>{r.name}</span>
            </div>
          )
        })}
        <svg className="links" width={width} height={HEAD + rows.length * ROW} style={{ top: -HEAD }}>
          {arrows.map((a) => (
            <g key={a.key} stroke={a.crit ? 'var(--critical)' : 'var(--ink-3)'} fill="none" strokeWidth="1.2">
              <path d={a.path} />
              <path d={a.toStart ? `M${a.x2 - 5},${a.y2 - 4} L${a.x2},${a.y2} L${a.x2 - 5},${a.y2 + 4}` : `M${a.x2 + 5},${a.y2 - 4} L${a.x2},${a.y2} L${a.x2 + 5},${a.y2 + 4}`} />
            </g>
          ))}
        </svg>
      </div>
    </div>
  )
}
