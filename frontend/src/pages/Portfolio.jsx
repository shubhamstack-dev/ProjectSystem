import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmt, signed, STATUS_NAMES } from '../api.js'
import Notice from '../components/Notice.jsx'
import ProjectEditor from '../components/ProjectEditor.jsx'
import { RowActions } from '../components/Icons.jsx'

const STATUS_CLS = ['acc', 'warn', 'done']

function initials(name) {
  return name.split(' ').map((s) => s[0]).slice(0, 2).join('').toUpperCase()
}

export default function Portfolio() {
  const nav = useNavigate()
  const [projects, setProjects] = useState(null)
  const [editing, setEditing] = useState(undefined) // undefined closed, null new, object edit
  const [error, setError] = useState(null)

  const load = () => api.projects().then(setProjects).catch(setError)
  useEffect(() => { load() }, [])

  async function remove(p) {
    if (!confirm(`Delete project ${p.code} "${p.name}" and everything in it?`)) return
    setError(null)
    try { await api.deleteProject(p.id); load() } catch (e) { setError(e) }
  }

  const list = projects || []
  const active = list.filter((p) => p.status === 0)
  const late = list.reduce((n, p) => n + p.lateCount, 0)
  const slipping = list.filter((p) => (p.endVarianceDays ?? 0) > 0).length
  const avg = active.length ? Math.round(active.reduce((n, p) => n + p.percentComplete, 0) / active.length) : 0

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Portfolio</h2>
          <p className="lead">Every project, with its planned end against the finish the schedule engine forecasts from the plan.</p>
        </div>
        <span className="grow" />
        <button className="pri" onClick={() => setEditing(null)}>+ New project</button>
      </div>
      <Notice error={error} onClose={() => setError(null)} />

      {projects && projects.length > 0 && (
        <div className="kpis">
          <div className="kpi"><div className="k">Projects</div><div className="v">{list.length}</div><div className="s">{active.length} active</div></div>
          <div className="kpi"><div className="k">Slipping</div><div className={'v' + (slipping ? ' bad' : ' good')}>{slipping}</div><div className="s">forecast past planned end</div></div>
          <div className="kpi"><div className="k">Late activities</div><div className={'v' + (late ? ' bad' : ' good')}>{late}</div><div className="s">across all projects</div></div>
          <div className="kpi"><div className="k">Average progress</div><div className="v">{avg}%</div><div className="s">active projects, duration-weighted</div></div>
        </div>
      )}

      {projects === null ? <p className="muted">Loading…</p> : projects.length === 0 ? (
        <div className="card"><div className="blank">
          <h3>No projects yet</h3>
          <p>Create one, then open its plan to build the outline: a milestone holds tasks, a task holds subtasks.</p>
          <button className="pri" onClick={() => setEditing(null)}>Create the first project</button>
        </div></div>
      ) : (
        <div className="card">
          <table className="grid">
            <thead>
              <tr>
                <th>Project</th><th>Status</th><th>Owner</th><th>Schedule</th>
                <th>Actual</th><th>Late / critical</th><th style={{ width: 150 }}>Progress</th><th className="act" />
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td>
                    <button className="link" style={{ fontWeight: 600, color: 'var(--ink)' }} onClick={() => nav(`/plan/${p.id}`)}>{p.name}</button>
                    <div className="sub">{p.code}{p.organisationName ? ` · ${p.organisationName}` : ''} · {p.teamSize} in team · {p.milestoneCount} milestones, {p.activityCount} activities, {p.workingDays} wd</div>
                  </td>
                  <td><span className={'pill ' + STATUS_CLS[p.status]}>{STATUS_NAMES[p.status]}</span></td>
                  <td>{p.ownerName ? <><span className="avatar">{initials(p.ownerName)}</span>{p.ownerName}</> : <span className="muted">—</span>}</td>
                  <td>{fmt(p.plannedStart)} → {p.plannedEnd ? fmt(p.plannedEnd) : '(no end)'}
                    <div className="sub">Forecast {p.forecastFinish ? fmt(p.forecastFinish) : '—'}{' '}
                      {p.endVarianceDays !== null && p.endVarianceDays !== undefined && (
                        <span className={'pill plain ' + (p.endVarianceDays > 0 ? 'crit' : 'done')}>{signed(p.endVarianceDays)} d</span>)}
                    </div>
                  </td>
                  <td>{p.actualStart ? <>{fmt(p.actualStart)}<div className="sub">{p.actualFinish ? `finished ${fmt(p.actualFinish)}` : 'in progress'}</div></> : <span className="muted">not started</span>}</td>
                  <td>{p.lateCount > 0 ? <span className="pill crit plain">{p.lateCount} late</span> : <span className="pill done plain">0 late</span>}<div className="sub">{p.criticalCount} critical</div></td>
                  <td><div className={'prog' + (p.percentComplete >= 100 ? ' done' : '')}><i style={{ width: `${p.percentComplete}%` }} /></div><div className="sub">{p.percentComplete}%</div></td>
                  <td className="act"><RowActions onOpen={() => nav(`/plan/${p.id}`)} onEdit={() => setEditing(p)} onDelete={() => remove(p)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing !== undefined && (
        <ProjectEditor project={editing} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); load() }} />
      )}
    </div>
  )
}
