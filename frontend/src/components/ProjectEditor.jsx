import { useEffect, useState } from 'react'
import Modal from './Modal.jsx'
import Notice from './Notice.jsx'
import { api, STATUS_NAMES, today } from '../api.js'

export default function ProjectEditor({ project, onSaved, onClose }) {
  const isNew = !project
  const [code, setCode] = useState(project?.code || '')
  const [name, setName] = useState(project?.name || '')
  const [status, setStatus] = useState(project?.status ?? 0)
  const [start, setStart] = useState(project?.plannedStart || today())
  const [end, setEnd] = useState(project?.plannedEnd || '')
  const [orgId, setOrgId] = useState(project?.organisationId || '')
  const [ownerId, setOwnerId] = useState(project?.ownerId || '')
  const [team, setTeam] = useState(new Set(project?.teamIds || []))
  const [holidays, setHolidays] = useState((project?.holidays || []).join('\n'))
  const [notes, setNotes] = useState(project?.notes || '')
  const [orgs, setOrgs] = useState([])
  const [people, setPeople] = useState([])
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([api.organisations(), api.people()]).then(([o, p]) => { setOrgs(o); setPeople(p) }).catch(setError)
  }, [])

  function toggle(id) {
    const next = new Set(team)
    next.has(id) ? next.delete(id) : next.add(id)
    setTeam(next)
  }

  async function save() {
    setSaving(true); setError(null)
    const body = {
      code: code.trim(), name: name.trim(), status: +status, plannedStart: start, plannedEnd: end || null,
      organisationId: orgId ? +orgId : null, ownerId: ownerId ? +ownerId : null,
      teamIds: [...team],
      holidays: holidays.split(/\s+/).map((s) => s.trim()).filter((s) => /^\d{4}-\d{2}-\d{2}$/.test(s)),
      notes: notes || null,
    }
    try {
      isNew ? await api.createProject(body) : await api.updateProject(project.id, body)
      onSaved()
    } catch (e) { setError(e) } finally { setSaving(false) }
  }

  return (
    <Modal title={isNew ? 'New project' : `Edit ${project.code}`} onClose={onClose} footer={
      <>
        <button onClick={onClose}>Cancel</button>
        <button className="pri" onClick={save} disabled={saving || !code.trim() || !name.trim() || !start}>{isNew ? 'Create project' : 'Save changes'}</button>
      </>
    }>
      <Notice error={error} onClose={() => setError(null)} />
      <div className="row2">
        <div className="fld"><label>Code</label><input autoFocus value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. P-104" /></div>
        <div className="fld"><label>Status</label>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>{STATUS_NAMES.map((s, i) => <option key={i} value={i}>{s}</option>)}</select>
        </div>
      </div>
      <div className="fld"><label>Project name</label><input value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div className="row2">
        <div className="fld"><label>Planned start</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
        <div className="fld"><label>Planned end</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
      </div>
      <div className="row2">
        <div className="fld"><label>Organisation</label>
          <select value={orgId} onChange={(e) => setOrgId(e.target.value)}><option value="">—</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
        </div>
        <div className="fld"><label>Owner</label>
          <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}><option value="">—</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        </div>
      </div>
      <div className="fld"><label>Project team</label>
        <div className="checks">
          {people.length === 0 && <span className="hint">No people yet — add them on the Team page.</span>}
          {people.map((p) => <label key={p.id}><input type="checkbox" checked={team.has(p.id)} onChange={() => toggle(p.id)} /> {p.name}</label>)}
        </div>
      </div>
      <div className="fld"><label>Non-working days (one date per line, YYYY-MM-DD; weekends are already excluded)</label>
        <textarea value={holidays} onChange={(e) => setHolidays(e.target.value)} placeholder="2026-01-26" /></div>
      <div className="fld"><label>Project notes</label><textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
    </Modal>
  )
}
