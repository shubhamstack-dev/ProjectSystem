import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmt } from '../api.js'
import Notice from '../components/Notice.jsx'
import Modal from '../components/Modal.jsx'
import { IcoOpen, IcoTrash } from '../components/Icons.jsx'

const cls = { Late: 'crit', Done: 'done', Active: 'acc', Due: 'warn' }
const initials = (n) => n.split(' ').map((s) => s[0]).slice(0, 2).join('').toUpperCase()

export default function Assignments() {
  const nav = useNavigate()
  const [rows, setRows] = useState(null)
  const [projects, setProjects] = useState([])          // [{ project, activities }]
  const [open, setOpen] = useState(new Set())            // expanded person ids
  const [assign, setAssign] = useState(null)             // person being assigned
  const [error, setError] = useState(null)

  async function load() {
    try {
      const [wl, ps] = await Promise.all([api.workload(), api.projects()])
      const details = await Promise.all(ps.map((p) => api.project(p.id)))
      setRows(wl)
      setProjects(details)
    } catch (e) { setError(e) }
  }
  useEffect(() => { load() }, [])

  // every leaf activity this person holds, across all projects
  function activitiesOf(personId) {
    const out = []
    for (const d of projects)
      for (const a of d.activities)
        if (!a.isSummary && a.assignees.some((x) => x.id === personId))
          out.push({ ...a, projectCode: d.project.code, projectName: d.project.name })
    return out.sort((x, y) => x.plannedStart.localeCompare(y.plannedStart))
  }

  function toggle(id) { const n = new Set(open); n.has(id) ? n.delete(id) : n.add(id); setOpen(n) }

  async function unassign(a, personId) {
    if (!confirm(`Remove this person from "${a.name}"?`)) return
    setError(null)
    try {
      await api.updateActivity(a.id, { assigneeIds: a.assignees.map((x) => x.id).filter((x) => x !== personId) })
      load()
    } catch (e) { setError(e) }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Assignments</h2>
          <p className="lead">Who is working on what, across every project. Expand a person to see their activities; an activity shared by several people contributes only its share of days to each.</p>
        </div>
      </div>
      <Notice error={error} onClose={() => setError(null)} />
      {rows === null ? <p className="muted">Loading…</p> : (
        <div className="card"><table className="grid">
          <thead><tr><th style={{ width: 30 }} /><th>Person</th><th>Role</th><th className="r">Projects</th><th className="r">Activities</th><th className="r">Working days</th><th className="r">Shared</th><th className="r">Late</th><th style={{ width: 150 }}>Progress</th><th className="act" /></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={10} className="muted">No people yet. Add them on the Team page.</td></tr>}
            {rows.map((r) => {
              const isOpen = open.has(r.personId)
              const acts = isOpen ? activitiesOf(r.personId) : []
              return [
                <tr key={r.personId} className="click" onClick={() => toggle(r.personId)}>
                  <td className="muted">{isOpen ? '▾' : '▸'}</td>
                  <td><span className="avatar">{initials(r.name)}</span>{r.name}</td>
                  <td className="muted">{r.roleName || '—'}</td>
                  <td className="r">{r.projects}</td><td className="r">{r.activities}</td><td className="r">{r.workingDays}</td>
                  <td className="r">{r.sharedCount || <span className="muted">0</span>}</td>
                  <td className="r">{r.lateCount > 0 ? <span className="pill crit plain">{r.lateCount}</span> : <span className="muted">0</span>}</td>
                  <td><div className="prog" style={{ maxWidth: 130 }}><i style={{ width: `${r.percentComplete}%` }} /></div><span className="sub">{r.percentComplete}%</span></td>
                  <td className="act"><button className="sm pri" onClick={(e) => { e.stopPropagation(); setAssign(r) }}>Assign…</button></td>
                </tr>,
                isOpen && (
                  <tr key={r.personId + '-x'}>
                    <td colSpan={10} style={{ padding: 0, background: '#fafbfd' }}>
                      {acts.length === 0 ? <div className="muted" style={{ padding: '10px 48px' }}>No activities assigned yet.</div> : (
                        <table className="grid" style={{ background: 'transparent' }}>
                          <thead><tr><th style={{ paddingLeft: 48, position: 'static' }}>Project</th><th style={{ position: 'static' }}>Activity</th><th style={{ position: 'static' }}>Planned</th><th className="r" style={{ position: 'static' }}>Days</th><th className="r" style={{ position: 'static' }}>Share</th><th className="r" style={{ position: 'static' }}>%</th><th style={{ position: 'static' }}>Status</th><th className="act" style={{ position: 'static' }} /></tr></thead>
                          <tbody>
                            {acts.map((a) => (
                              <tr key={a.id}>
                                <td style={{ paddingLeft: 48 }}>{a.projectCode}<div className="sub">{a.projectName}</div></td>
                                <td><span className="muted">{a.wbs}</span> {a.name}{a.assignees.length > 1 && <div className="sub">with {a.assignees.filter((x) => x.id !== r.personId).map((x) => x.name).join(', ')}</div>}</td>
                                <td>{fmt(a.plannedStart)} → {fmt(a.plannedFinish)}</td>
                                <td className="r">{a.duration}</td>
                                <td className="r">{a.assignees.length > 1 ? (a.duration / a.assignees.length).toFixed(1) : a.duration}</td>
                                <td className="r">{a.percentComplete}</td>
                                <td><span className={'pill ' + (cls[a.status] || '')}>{a.status}</span></td>
                                <td className="act"><span className="actions">
                                  <button className="ib" title="Open plan" onClick={() => nav(`/plan/${a.projectId}`)}><IcoOpen /></button>
                                  <button className="ib danger" title="Remove from this activity" onClick={() => unassign(a, r.personId)}><IcoTrash /></button>
                                </span></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </td>
                  </tr>
                ),
              ]
            })}
          </tbody>
        </table></div>
      )}

      {assign && <AssignDialog person={assign} projects={projects} onClose={() => setAssign(null)} onSaved={() => { setAssign(null); setOpen(new Set([...open, assign.personId])); load() }} />}
    </div>
  )
}

function AssignDialog({ person, projects, onClose, onSaved }) {
  const [projectId, setProjectId] = useState(projects[0]?.project.id || '')
  const [activityId, setActivityId] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const detail = projects.find((d) => d.project.id === +projectId)
  const choices = (detail?.activities || []).filter((a) => !a.isSummary && !a.assignees.some((x) => x.id === person.personId))

  async function save() {
    const a = detail.activities.find((x) => x.id === +activityId)
    setBusy(true); setError(null)
    try {
      await api.updateActivity(a.id, { assigneeIds: [...a.assignees.map((x) => x.id), person.personId] })
      onSaved()
    } catch (e) { setError(e) } finally { setBusy(false) }
  }

  return (
    <Modal title={`Assign ${person.name}`} onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="pri" disabled={busy || !activityId} onClick={save}>Assign</button></>}>
      <Notice error={error} onClose={() => setError(null)} />
      {projects.length === 0 ? <p className="muted">No projects yet.</p> : (
        <>
          <div className="fld"><label>Project</label>
            <select value={projectId} onChange={(e) => { setProjectId(e.target.value); setActivityId('') }}>
              {projects.map((d) => <option key={d.project.id} value={d.project.id}>{d.project.code} · {d.project.name}</option>)}
            </select>
          </div>
          <div className="fld"><label>Activity</label>
            <select value={activityId} onChange={(e) => setActivityId(e.target.value)}>
              <option value="">{choices.length ? 'Choose an activity…' : 'Nothing left to assign in this project'}</option>
              {choices.map((a) => <option key={a.id} value={a.id}>{a.wbs} {a.name} ({a.duration} wd, {fmt(a.plannedStart)})</option>)}
            </select>
            <span className="hint">Only leaf activities are listed; summaries take their dates from their children. Assigning is always allowed, even on a locked plan.</span>
          </div>
        </>
      )}
    </Modal>
  )
}
