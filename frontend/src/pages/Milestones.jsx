import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmt, signed } from '../api.js'
import Notice from '../components/Notice.jsx'
import { RowActions } from '../components/Icons.jsx'

const cls = { Achieved: 'done', 'Past target': 'crit', Overdue: 'crit', 'In progress': 'acc' }

export default function Milestones() {
  const nav = useNavigate()
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    (async () => {
      try {
        const projects = await api.projects()
        const all = []
        for (const p of projects) {
          const d = await api.project(p.id)
          for (const a of d.activities) if (a.level === 0) all.push({ ...a, projectCode: p.code, projectName: p.name })
        }
        setRows(all)
      } catch (e) { setError(e) }
    })()
  }, [])

  return (
    <div className="page">
      <h2>Milestones</h2>
      <p className="lead">Every milestone across the portfolio: the target date it was committed to, the finish the schedule forecasts, and what actually happened.</p>
      <Notice error={error} />
      {rows === null ? <p className="muted">Loading…</p> : (
        <div className="card"><table className="grid">
          <thead><tr><th>Project</th><th>Milestone</th><th>Target</th><th>Forecast</th><th className="r">Δ target</th><th>Actual</th><th className="r">%</th><th>Status</th><th className="act" /></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={9} className="muted">No milestones yet.</td></tr>}
            {rows.map((m) => (
              <tr key={m.id}>
                <td>{m.projectCode}<div className="muted">{m.projectName}</div></td>
                <td>{m.wbs} {m.name}</td>
                <td>{m.targetDate ? fmt(m.targetDate) : <span className="muted">none</span>}</td>
                <td>{fmt(m.plannedFinish)}</td>
                <td className="r">{m.targetVarianceDays != null && <span className={'pill ' + (m.targetVarianceDays > 0 ? 'crit' : 'done')}>{signed(m.targetVarianceDays)} wd</span>}</td>
                <td>{fmt(m.actualFinish)}</td>
                <td className="r">{m.percentComplete}</td>
                <td><span className={'pill ' + (cls[m.status] || '')}>{m.status}</span></td>
                <td className="act"><RowActions onOpen={() => nav(`/plan/${m.projectId}`)} /></td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </div>
  )
}
