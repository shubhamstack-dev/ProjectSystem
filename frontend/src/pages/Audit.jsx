import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Notice from '../components/Notice.jsx'

const KINDS = ['Project', 'Milestone', 'Task', 'Subtask', 'Organisation', 'Role', 'Person']

export default function Audit() {
  const [rows, setRows] = useState(null)
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [kind, setKind] = useState('')
  const [q, setQ] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => { api.projects().then(setProjects).catch(() => {}) }, [])
  useEffect(() => {
    const t = setTimeout(() => {
      const params = { take: 500 }
      if (projectId) params.projectId = projectId
      if (kind) params.kind = kind
      if (q) params.q = q
      api.audit(params).then(setRows).catch(setError)
    }, 200)
    return () => clearTimeout(t)
  }, [projectId, kind, q])

  return (
    <div className="page">
      <h2>Audit trail</h2>
      <p className="lead">Append-only. Every create, edit, move, deletion and refusal, newest first, with who did it and the before → after values.</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">All projects</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.code}</option>)}</select>
        <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All kinds</option>{KINDS.map((k) => <option key={k}>{k}</option>)}</select>
        <input placeholder="Search name, detail or person" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
      </div>
      <Notice error={error} />
      {rows === null ? <p className="muted">Loading…</p> : (
        <div className="card"><table className="grid">
          <thead><tr><th>When (UTC)</th><th>Who</th><th>Action</th><th>Kind</th><th>Name</th><th>Project</th><th>Detail</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={7} className="muted">Nothing recorded yet.</td></tr>}
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="muted">{r.timestampUtc.replace('T', ' ').slice(0, 19)}</td>
                <td>{r.who}</td>
                <td>{/Refused/.test(r.action) ? <span className="pill crit">{r.action}</span> : r.action === 'PlanLocked' ? <span className="pill warn">{r.action}</span> : r.action}</td>
                <td className="muted">{r.entityKind}</td>
                <td>{r.entityName}</td>
                <td className="muted">{r.projectCode || ''}</td>
                <td className="wrap">{r.detail || ''}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </div>
  )
}
