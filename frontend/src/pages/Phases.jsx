import { useEffect, useState } from 'react'
import { api, fmt } from '../api.js'
import Modal from '../components/Modal.jsx'
import Notice from '../components/Notice.jsx'
import { RowActions } from '../components/Icons.jsx'

/* The Phases section: split a project into phases (Design, Build,
   Commissioning ...) and, per phase, fill the roles & responsibilities table -
   which role, with which responsibilities, is carried by which team member. */

export default function Phases() {
  const [projects, setProjects] = useState([])
  const [roles, setRoles] = useState([])
  const [people, setPeople] = useState([])
  const [projectId, setProjectId] = useState('')
  const [phases, setPhases] = useState([])
  const [dlg, setDlg] = useState(null)   // { row: phase|null }
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([api.projects(), api.roles(), api.people()])
      .then(([pr, r, pe]) => {
        setProjects(pr); setRoles(r); setPeople(pe)
        if (pr.length && !projectId) setProjectId(String(pr[0].id))
      }).catch(setError)
  }, [])
  const load = (pid = projectId) => (pid ? api.phases(pid).then(setPhases).catch(setError) : setPhases([]))
  useEffect(() => { load() }, [projectId])

  async function removePhase(p) {
    if (!confirm(`Delete phase "${p.name}" and its ${p.assignments.length} assignment(s)?`)) return
    try { await api.deletePhase(p.id); load() } catch (e) { setError(e) }
  }
  async function move(p, direction) {
    try { await api.movePhase(p.id, direction); load() } catch (e) { setError(e) }
  }

  return (
    <div className="page">
      <h2>Phases</h2>
      <p className="lead">Split the project into phases and define its roles &amp; responsibilities table:
        per phase, assign each role - with the responsibilities defined on it - to a team member.</p>
      <Notice error={error} onClose={() => setError(null)} />

      <div className="fld" style={{ maxWidth: 420, marginBottom: 12 }}>
        <label>Project</label>
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">— choose a project —</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
        </select>
      </div>

      {projectId && (
        <div className="stack">
          <div>
            <button className="sm pri" onClick={() => setDlg({ row: null })}>+ Phase</button>
          </div>
          {phases.length === 0 && <div className="muted">No phases yet — add the first one.</div>}
          {phases.map((p, i) => (
            <section className="panel" key={p.id}>
              <div className="ph">
                <span className="phasebar" style={{ background: p.colour }} />
                {p.name}
                <span className="hint" style={{ fontWeight: 400 }}>
                  &nbsp;{p.startDate || p.endDate ? `${fmt(p.startDate) || '…'} – ${fmt(p.endDate) || '…'}` : ''}</span>
                <span style={{ flex: 1 }} />
                <button className="sm" disabled={i === 0} onClick={() => move(p, 'up')}>↑</button>{' '}
                <button className="sm" disabled={i === phases.length - 1} onClick={() => move(p, 'down')}>↓</button>{' '}
                <button className="sm" onClick={() => setDlg({ row: p })}>Edit</button>{' '}
                <button className="sm" onClick={() => removePhase(p)}>Delete</button>
              </div>
              <AssignTable phase={p} roles={roles} people={people}
                onChanged={load} onError={setError} />
            </section>
          ))}
        </div>
      )}

      {dlg && <PhaseDialog row={dlg.row} projectId={projectId} onClose={() => setDlg(null)}
        onSaved={() => { setDlg(null); load() }} />}
    </div>
  )
}

function AssignTable({ phase, roles, people, onChanged, onError }) {
  const [roleId, setRoleId] = useState('')
  const [personId, setPersonId] = useState('')
  const [notes, setNotes] = useState('')
  const teamRoles = roles.filter((r) => !r.isCustomer)

  async function add() {
    try {
      await api.addPhaseAssignment(phase.id, { roleId: +roleId, personId: +personId, notes: notes || null })
      setRoleId(''); setPersonId(''); setNotes('')
      onChanged()
    } catch (e) { onError(e) }
  }
  async function remove(a) {
    if (!confirm(`Remove ${a.personName} as ${a.roleName} in "${phase.name}"?`)) return
    try { await api.deletePhaseAssignment(a.id); onChanged() } catch (e) { onError(e) }
  }

  return (
    <table className="grid">
      <thead><tr><th>Role</th><th>Responsibilities</th><th>Assigned to</th><th>Notes for this phase</th><th className="act" /></tr></thead>
      <tbody>
        {phase.assignments.length === 0 && <tr><td colSpan={5} className="muted">No roles assigned in this phase yet.</td></tr>}
        {phase.assignments.map((a) => (
          <tr key={a.id}>
            <td style={{ fontWeight: 600 }}><span className="swatch" style={{ background: a.roleColour }} />{a.roleName}</td>
            <td className="wrap muted">{a.responsibilities || '—'}</td>
            <td>{a.personName}</td>
            <td className="wrap muted">{a.notes || ''}</td>
            <td className="act"><RowActions onDelete={() => remove(a)} /></td>
          </tr>
        ))}
        <tr>
          <td>
            <select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
              <option value="">+ role…</option>
              {teamRoles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </td>
          <td className="muted wrap">{teamRoles.find((r) => String(r.id) === roleId)?.responsibilities || ''}</td>
          <td>
            <select value={personId} onChange={(e) => setPersonId(e.target.value)}>
              <option value="">person…</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </td>
          <td><input placeholder="optional" value={notes} onChange={(e) => setNotes(e.target.value)} /></td>
          <td className="act"><button className="sm pri" disabled={!roleId || !personId} onClick={add}>Assign</button></td>
        </tr>
      </tbody>
    </table>
  )
}

function PhaseDialog({ row, projectId, onClose, onSaved }) {
  const [name, setName] = useState(row?.name || '')
  const [startDate, setStartDate] = useState(row?.startDate || '')
  const [endDate, setEndDate] = useState(row?.endDate || '')
  const [colour, setColour] = useState(row?.colour || '#2F6F9E')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const body = { name: name.trim(), startDate: startDate || null, endDate: endDate || null, colour }
  async function save() {
    setBusy(true); setError(null)
    try { row ? await api.updatePhase(row.id, body) : await api.createPhase(projectId, body); onSaved() }
    catch (e) { setError(e) } finally { setBusy(false) }
  }
  return (
    <Modal title={row ? 'Edit phase' : 'New phase'} onClose={onClose}
      footer={<><button onClick={onClose}>Cancel</button>
        <button className="pri" disabled={busy || !name.trim()} onClick={save}>{row ? 'Save changes' : 'Create phase'}</button></>}>
      <Notice error={error} onClose={() => setError(null)} />
      <div className="row2">
        <div className="fld"><label>Name</label><input autoFocus placeholder="e.g. Design" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="fld"><label>Colour</label><input type="color" value={colour} onChange={(e) => setColour(e.target.value.toUpperCase())} /></div>
      </div>
      <div className="row2">
        <div className="fld"><label>Starts</label><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></div>
        <div className="fld"><label>Ends</label><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></div>
      </div>
    </Modal>
  )
}
