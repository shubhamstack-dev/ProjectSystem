import { useEffect, useState } from 'react'
import { api, fmt } from '../api.js'
import Modal from '../components/Modal.jsx'
import Notice from '../components/Notice.jsx'
import { RowActions } from '../components/Icons.jsx'

/* Roles → Customer Roles.
   Top: define the customer roles (who at the customer side signs off).
   Below: the customer workspace - project status, and approve / reject of the
   actual dates the organisation's employees entered, line item by line item. */

const StatusPill = ({ s }) => (
  <span className={'pill ' + (s === 'Approved' ? 'ok' : s === 'Rejected' ? 'rej' : 'pend')}>{s}</span>
)

export default function CustomerRoles() {
  const [roles, setRoles] = useState([])
  const [people, setPeople] = useState([])
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [lines, setLines] = useState([])
  const [dlg, setDlg] = useState(null)          // role dialog
  const [decide, setDecide] = useState(null)    // { line, kind: 'approve'|'reject' }
  const [error, setError] = useState(null)

  const loadRoles = () => Promise.all([api.roles(), api.people()])
    .then(([r, p]) => { setRoles(r.filter((x) => x.isCustomer)); setPeople(p) }).catch(setError)
  const loadProjects = () => api.customerProjects().then(setProjects).catch(setError)
  const loadLines = (pid) => (pid ? api.customerLines(pid).then(setLines).catch(setError) : setLines([]))

  useEffect(() => { loadRoles(); loadProjects() }, [])
  useEffect(() => { loadLines(projectId) }, [projectId])

  async function removeRole(r) {
    if (!confirm(`Delete customer role "${r.name}"? ${r.peopleCount} people will be left without a role.`)) return
    setError(null)
    try { await api.deleteRole(r.id); loadRoles() } catch (e) { setError(e) }
  }

  const project = projects.find((p) => String(p.id) === String(projectId))
  const holders = (roleId) => people.filter((p) => p.roleId === roleId).map((p) => p.name).join(', ')

  return (
    <div className="page">
      <h2>Customer Roles</h2>
      <p className="lead">Customer roles can view project status and approve or reject - line item by
        line item - the actual dates entered by the organisation's employees. Decisions land in the audit trail.</p>
      <Notice error={error} onClose={() => setError(null)} />

      <div className="stack">
        <section className="panel">
          <div className="ph">Customer roles <button className="sm pri" onClick={() => setDlg({ row: null })}>+ Customer role</button></div>
          <table className="grid"><thead><tr><th>Role</th><th>Responsibilities</th><th>Held by</th><th className="act" /></tr></thead>
            <tbody>
              {roles.length === 0 && <tr><td colSpan={4} className="muted">None yet. Create one, then set it as a person's role on the Team page.</td></tr>}
              {roles.map((r) => (
                <tr key={r.id}>
                  <td style={{ fontWeight: 600 }}><span className="swatch" style={{ background: r.colour }} />{r.name}</td>
                  <td className="wrap muted">{r.responsibilities || ''}</td>
                  <td className="muted">{holders(r.id) || '—'}</td>
                  <td className="act"><RowActions onEdit={() => setDlg({ row: r })} onDelete={() => removeRole(r)} /></td>
                </tr>
              ))}
            </tbody></table>
        </section>

        <section className="panel">
          <div className="ph">Customer workspace — project status &amp; date approvals</div>
          <div style={{ padding: '10px 14px' }}>
            <div className="fld" style={{ maxWidth: 420 }}>
              <label>Project</label>
              <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">— choose a project —</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} · {p.name}{p.pendingCount ? ` (${p.pendingCount} waiting)` : ''}
                  </option>
                ))}
              </select>
            </div>

            {project && (
              <div className="cards" style={{ display: 'flex', gap: 18, flexWrap: 'wrap', margin: '8px 0 14px' }}>
                <div><span className="hint">Status</span><div style={{ fontWeight: 700 }}>{project.status}</div></div>
                <div><span className="hint">Complete</span><div style={{ fontWeight: 700 }}>{project.percentComplete}%</div></div>
                <div><span className="hint">Planned end</span><div style={{ fontWeight: 700 }}>{fmt(project.plannedEnd) || '—'}</div></div>
                <div><span className="hint">Forecast finish</span><div style={{ fontWeight: 700 }}>
                  {fmt(project.forecastFinish) || '—'}
                  {project.endVarianceDays != null && project.endVarianceDays !== 0 &&
                    <span className={'pill plain ' + (project.endVarianceDays > 0 ? 'rej' : 'ok')} style={{ marginLeft: 6 }}>
                      {project.endVarianceDays > 0 ? `+${project.endVarianceDays}d late` : `${project.endVarianceDays}d early`}</span>}
                </div></div>
                <div><span className="hint">Waiting for you</span><div style={{ fontWeight: 700 }}>{project.pendingCount}</div></div>
              </div>
            )}
          </div>

          {projectId !== '' && (
            <table className="grid">
              <thead><tr><th>WBS</th><th>Line item</th><th>Planned</th><th>Actual dates entered</th>
                <th>Entered by</th><th>Approval</th><th className="act" /></tr></thead>
              <tbody>
                {lines.length === 0 && <tr><td colSpan={7} className="muted">
                  No line items with actual dates yet — there is nothing to sign off.</td></tr>}
                {lines.map((l) => (
                  <tr key={l.activityId}>
                    <td className="muted">{l.wbs}</td>
                    <td style={{ fontWeight: 600 }}>{l.name}<div className="hint">{l.kind} · {l.percentComplete}%</div></td>
                    <td className="muted">{fmt(l.plannedStart)} – {fmt(l.plannedFinish)}</td>
                    <td>{l.actualStart ? `started ${fmt(l.actualStart)}` : ''}
                      {l.actualStart && l.actualFinish ? ' · ' : ''}
                      {l.actualFinish ? `finished ${fmt(l.actualFinish)}` : ''}</td>
                    <td className="muted">{l.submittedBy || '—'}</td>
                    <td><StatusPill s={l.approvalStatus} />
                      {l.comment && <div className="hint wrap">{l.comment}</div>}
                      {l.decidedBy && <div className="hint">by {l.decidedBy}</div>}</td>
                    <td className="act" style={{ whiteSpace: 'nowrap' }}>
                      {l.approvalStatus !== 'Approved' &&
                        <button className="sm pri" onClick={() => setDecide({ line: l, kind: 'approve' })}>Approve</button>}{' '}
                      {l.approvalStatus !== 'Rejected' &&
                        <button className="sm" onClick={() => setDecide({ line: l, kind: 'reject' })}>Reject</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      {dlg && <CustomerRoleDialog row={dlg.row} onClose={() => setDlg(null)}
        onSaved={() => { setDlg(null); loadRoles() }} />}
      {decide && <DecisionDialog line={decide.line} kind={decide.kind} onClose={() => setDecide(null)}
        onDone={() => { setDecide(null); loadLines(projectId); loadProjects() }} />}
    </div>
  )
}

function CustomerRoleDialog({ row, onClose, onSaved }) {
  const [name, setName] = useState(row?.name || '')
  const [responsibilities, setResponsibilities] = useState(row?.responsibilities || '')
  const [colour, setColour] = useState(row?.colour || '#7A3FA0')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const body = { name: name.trim(), responsibilities: responsibilities || null, colour,
                 views: ['customer'], organisationId: row?.organisationId ?? null, isCustomer: true }
  async function save() {
    setBusy(true); setError(null)
    try { row ? await api.updateRole(row.id, body) : await api.createRole(body); onSaved() }
    catch (e) { setError(e) } finally { setBusy(false) }
  }
  return (
    <Modal title={row ? 'Edit customer role' : 'New customer role'} onClose={onClose}
      footer={<><button onClick={onClose}>Cancel</button>
        <button className="pri" disabled={busy || !name.trim()} onClick={save}>{row ? 'Save changes' : 'Create role'}</button></>}>
      <Notice error={error} onClose={() => setError(null)} />
      <div className="row2">
        <div className="fld"><label>Name</label><input autoFocus placeholder="e.g. Customer PM" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="fld"><label>Colour</label><input type="color" value={colour} onChange={(e) => setColour(e.target.value.toUpperCase())} /></div>
      </div>
      <div className="fld"><label>Responsibilities</label>
        <textarea placeholder="e.g. Reviews progress and signs off actual dates line by line"
          value={responsibilities} onChange={(e) => setResponsibilities(e.target.value)} /></div>
      <span className="hint">Access: view project status; approve / reject actual dates per line item.</span>
    </Modal>
  )
}

function DecisionDialog({ line, kind, onClose, onDone }) {
  const [comment, setComment] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const approve = kind === 'approve'
  async function go() {
    setBusy(true); setError(null)
    try {
      approve ? await api.approveLine(line.activityId, comment || null)
              : await api.rejectLine(line.activityId, comment)
      onDone()
    } catch (e) { setError(e) } finally { setBusy(false) }
  }
  return (
    <Modal title={`${approve ? 'Approve' : 'Reject'} actual dates — ${line.wbs} ${line.name}`} onClose={onClose}
      footer={<><button onClick={onClose}>Cancel</button>
        <button className="pri" disabled={busy || (!approve && comment.trim().length < 3)} onClick={go}>
          {approve ? 'Approve' : 'Reject and send back'}</button></>}>
      <Notice error={error} onClose={() => setError(null)} />
      <p className="muted" style={{ marginTop: 0 }}>
        {line.actualStart ? `Started ${fmt(line.actualStart)}` : ''}
        {line.actualStart && line.actualFinish ? ' · ' : ''}
        {line.actualFinish ? `finished ${fmt(line.actualFinish)}` : ''} — entered by {line.submittedBy || 'the team'}.</p>
      <div className="fld"><label>Comment {approve ? '(optional)' : '(required — say what is wrong)'}</label>
        <textarea autoFocus value={comment} onChange={(e) => setComment(e.target.value)}
          placeholder={approve ? 'e.g. Matches the site log.' : 'e.g. Work finished on the 12th, not the 10th — see the inspection report.'} /></div>
    </Modal>
  )
}
