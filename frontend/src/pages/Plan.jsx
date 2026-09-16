import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, DEP_TYPES, fmt, signed } from '../api.js'
import Notice from '../components/Notice.jsx'
import Gantt from '../components/Gantt.jsx'
import ActivityEditor from '../components/ActivityEditor.jsx'

const ZOOM = [['30', 'Day'], ['12', 'Week'], ['3.6', 'Month'], ['1.5', 'Quarter']]

function statusPill(s) {
  const cls = { Late: 'crit', Overdue: 'crit', 'Past target': 'crit', Done: 'done', Achieved: 'done', Active: 'acc', 'In progress': 'acc', Due: 'warn' }[s] || ''
  return <span className={'pill ' + cls}>{s}</span>
}

export default function Plan() {
  const { projectId } = useParams()
  const nav = useNavigate()
  const [projects, setProjects] = useState([])
  const [detail, setDetail] = useState(null)
  const [people, setPeople] = useState([])
  const [roles, setRoles] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [columns, setColumns] = useState('plan')
  const [px, setPx] = useState('12')
  const [editor, setEditor] = useState(null) // { level, afterId } | { activity }
  const [error, setError] = useState(null)

  useEffect(() => {
    api.projects().then((ps) => {
      setProjects(ps)
      if (!projectId && ps.length) nav(`/plan/${ps[0].id}`, { replace: true })
    }).catch(setError)
    api.people().then(setPeople).catch(() => {})
    api.roles().then(setRoles).catch(() => {})
  }, [])

  const load = useCallback(() => {
    if (!projectId) return
    api.project(projectId).then(setDetail).catch(setError)
  }, [projectId])
  useEffect(() => { setSelectedId(null); load() }, [load])

  const rows = detail?.activities || []
  const selected = rows.find((a) => a.id === selectedId) || null

  async function act(fn) {
    setError(null)
    try { await fn(); load() } catch (e) { setError(e) }
  }

  function remove() {
    if (!selected) return
    if (!confirm(`Delete "${selected.name}"${selected.isSummary ? ' and everything beneath it' : ''}?`)) return
    act(() => api.deleteActivity(selected.id))
  }

  if (!projectId || (projects.length === 0 && !detail)) {
    return (
      <div className="page"><div className="card"><div className="blank">
        <h3>No project open</h3>
        <p>A plan needs a project to hang from. Create one on the Portfolio page, then build the outline here.</p>
        <button className="pri" onClick={() => nav('/')}>Go to Portfolio</button>
      </div></div></div>
    )
  }

  const showTrack = columns !== 'plan'
  const showPlan = columns !== 'track'

  return (
    <>
      <div className="bar">
        <label>Project</label>
        <select value={projectId} onChange={(e) => nav(`/plan/${e.target.value}`)}>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
        </select>
        <div className="sep" />
        <span className="grp">
          <button className="pri" onClick={() => setEditor({ level: 0, afterId: selected?.id })}>+ Milestone</button>
          <button onClick={() => setEditor({ level: 1, afterId: selected?.id })} disabled={!rows.length} title={rows.length ? '' : 'Add a milestone first'}>+ Task</button>
          <button onClick={() => setEditor({ level: 2, afterId: selected?.id })} disabled={!selected || selected.level === 0}>+ Subtask</button>
        </span>
        <button onClick={() => setEditor({ activity: selected })} disabled={!selected}>Edit…</button>
        <button className="danger" onClick={remove} disabled={!selected}>Delete</button>
        <div className="sep" />
        <span className="grp">
          <button disabled={!selected} title="Move up" onClick={() => act(() => api.moveActivity(selected.id, 'up'))}>↑</button>
          <button disabled={!selected} title="Move down" onClick={() => act(() => api.moveActivity(selected.id, 'down'))}>↓</button>
          <button disabled={!selected} title="Outdent (one level up)" onClick={() => act(() => api.moveActivity(selected.id, 'outdent'))}>←</button>
          <button disabled={!selected} title="Indent (under the row above)" onClick={() => act(() => api.moveActivity(selected.id, 'indent'))}>→</button>
        </span>
        <div className="sep" />
        <button onClick={() => { if (confirm('Freeze the current schedule as the baseline?')) act(() => api.baseline(projectId)) }}>Baseline</button>
        <label>Columns</label>
        <select value={columns} onChange={(e) => setColumns(e.target.value)}>
          <option value="plan">Plan</option><option value="track">Tracking</option><option value="all">All</option>
        </select>
        <label>Zoom</label>
        <select value={px} onChange={(e) => setPx(e.target.value)}>{ZOOM.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      </div>

      <Notice error={error} onClose={() => setError(null)} />
      {detail?.scheduleWarning && <div className="notice warn">{detail.scheduleWarning}</div>}

      <div className="work">
        <div className="gridpane">
          <table className="grid">
            <thead>
              <tr>
                <th className="r">WBS</th><th>Activity</th><th>Kind</th><th>Mode</th><th className="r">Days</th>
                <th>Plan start</th><th>Plan finish</th>
                {showTrack && <><th>Act. start</th><th>Act. finish</th><th className="r">Var</th></>}
                {showPlan && <><th>Target</th><th className="r">Δ tgt</th><th>Links</th></>}
                <th className="r">%</th><th>Assigned to</th><th className="r">Float</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={20} className="muted" style={{ padding: 20 }}>Empty plan. Start with “+ Milestone”, then add tasks beneath it.</td></tr>
              )}
              {rows.map((a) => (
                <tr key={a.id} className={'click' + (a.isSummary ? ' summary' : '') + (a.id === selectedId ? ' sel' : '')}
                    onClick={() => setSelectedId(a.id)} onDoubleClick={() => setEditor({ activity: a })}>
                  <td className="r muted">{a.wbs}</td>
                  <td className={`indent-${a.level}`}>{a.name}{a.isLocked && <span className="lock" title="Plan locked: work recorded">🔒</span>}</td>
                  <td className="muted">{a.kind}</td>
                  <td className="muted">{a.mode === 1 ? 'Man' : 'Auto'}</td>
                  <td className="r">{a.duration}</td>
                  <td>{fmt(a.plannedStart)}</td><td>{fmt(a.plannedFinish)}</td>
                  {showTrack && <>
                    <td>{fmt(a.actualStart)}</td><td>{fmt(a.actualFinish)}</td>
                    <td className="r">{a.finishVarianceDays !== null && a.finishVarianceDays !== undefined && <span className={'pill ' + (a.finishVarianceDays > 0 ? 'crit' : 'done')}>{signed(a.finishVarianceDays)}</span>}</td>
                  </>}
                  {showPlan && <>
                    <td>{fmt(a.targetDate)}</td>
                    <td className="r">{a.targetVarianceDays !== null && a.targetVarianceDays !== undefined && <span className={'pill ' + (a.targetVarianceDays > 0 ? 'crit' : 'done')}>{signed(a.targetVarianceDays)}</span>}</td>
                    <td className="muted">{a.dependencies.map((d) => `${d.predecessorWbs}${d.type ? DEP_TYPES[d.type] : ''}${d.lag ? signed(d.lag) : ''}`).join(', ')}</td>
                  </>}
                  <td className="r">{a.percentComplete}</td>
                  <td className="muted">{a.assignees.map((p) => p.name.split(' ')[0]).join(', ')}</td>
                  <td className="r">{a.isSummary ? '' : a.isCritical ? <span className="pill crit">0</span> : a.totalFloat}</td>
                  <td>{a.isSummary && a.level > 0 ? '' : statusPill(a.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="ganttpane">
          {rows.length > 0 && <Gantt rows={rows} holidays={detail.holidays} selectedId={selectedId} onSelect={setSelectedId} pxPerDay={+px} projectStart={detail.project.plannedStart} />}
        </div>
      </div>

      {detail && (
        <div className="foot">
          <span>Activities <b>{rows.filter((a) => !a.isSummary).length}</b></span>
          <span>Critical <b>{rows.filter((a) => a.isCritical).length}</b></span>
          <span>Late <b>{detail.project.lateCount}</b></span>
          <span>Forecast finish <b>{fmt(detail.project.forecastFinish)}</b>{detail.project.endVarianceDays != null && <> ({signed(detail.project.endVarianceDays)} d vs plan)</>}</span>
          <span>Progress <b>{detail.project.percentComplete}%</b></span>
          <span className="muted">Double-click a row to edit it.</span>
        </div>
      )}

      {editor && (
        <ActivityEditor
          projectId={+projectId}
          level={editor.level} afterId={editor.afterId} activity={editor.activity}
          people={people} roles={roles}
          onClose={() => setEditor(null)}
          onSaved={() => { setEditor(null); load() }}
        />
      )}
    </>
  )
}
