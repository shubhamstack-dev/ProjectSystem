import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Modal from '../components/Modal.jsx'
import Notice from '../components/Notice.jsx'
import { RowActions } from '../components/Icons.jsx'

const VIEWS = [['portfolio', 'Portfolio'], ['plan', 'Plan'], ['miles', 'Milestones'], ['assign', 'Assignments'], ['team', 'Team'], ['audit', 'Audit']]

export default function Team() {
  const [orgs, setOrgs] = useState([])
  const [roles, setRoles] = useState([])
  const [people, setPeople] = useState([])
  const [dlg, setDlg] = useState(null) // { kind: 'org'|'role'|'person', row: null|object }
  const [error, setError] = useState(null)

  const load = () => Promise.all([api.organisations(), api.roles(), api.people()])
    .then(([o, r, p]) => { setOrgs(o); setRoles(r); setPeople(p) }).catch(setError)
  useEffect(() => { load() }, [])

  async function remove(kind, row) {
    const warn = {
      org: `Delete organisation "${row.name}"? Its roles and projects stay but lose the link.`,
      role: `Delete role "${row.name}"? ${row.peopleCount} people will be left without a role.`,
      person: `Delete "${row.name}"? They are removed from every team and assignment.`,
    }[kind]
    if (!confirm(warn)) return
    setError(null)
    try {
      if (kind === 'org') await api.deleteOrganisation(row.id)
      if (kind === 'role') await api.deleteRole(row.id)
      if (kind === 'person') await api.deletePerson(row.id)
      load()
    } catch (e) { setError(e) }
  }

  return (
    <div className="page">
      <h2>Team</h2>
      <p className="lead">Organisations hold roles, roles describe responsibilities and which views a person can see, and people hold one role each.</p>
      <Notice error={error} onClose={() => setError(null)} />

      <div className="stack">
        <section className="panel">
          <div className="ph">Organisations <button className="sm pri" onClick={() => setDlg({ kind: 'org', row: null })}>+ Organisation</button></div>
          <table className="grid"><thead><tr><th>Name</th><th>Description</th><th className="r">Roles</th><th className="r">People</th><th className="r">Projects</th><th className="act" /></tr></thead>
            <tbody>
              {orgs.length === 0 && <tr><td colSpan={6} className="muted">None yet.</td></tr>}
              {orgs.map((o) => (
                <tr key={o.id}>
                  <td style={{ fontWeight: 600 }}>{o.name}</td><td className="wrap muted">{o.description || ''}</td>
                  <td className="r">{o.roleCount}</td><td className="r">{o.peopleCount}</td><td className="r">{o.projectCount}</td>
                  <td className="act"><RowActions onEdit={() => setDlg({ kind: 'org', row: o })} onDelete={() => remove('org', o)} /></td>
                </tr>
              ))}
            </tbody></table>
        </section>

        <section className="panel">
          <div className="ph">Roles <button className="sm pri" onClick={() => setDlg({ kind: 'role', row: null })}>+ Role</button></div>
          <table className="grid"><thead><tr><th>Role</th><th>Responsibilities</th><th>Organisation</th><th>Views</th><th className="r">People</th><th className="act" /></tr></thead>
            <tbody>
              {roles.length === 0 && <tr><td colSpan={6} className="muted">None yet.</td></tr>}
              {roles.map((r) => (
                <tr key={r.id}>
                  <td style={{ fontWeight: 600 }}><span className="swatch" style={{ background: r.colour }} />{r.name}</td><td className="wrap muted">{r.responsibilities || ''}</td>
                  <td className="muted">{r.organisationName || '—'}</td>
                  <td className="tags">{r.views.map((v) => <span key={v}>{v}</span>)}</td>
                  <td className="r">{r.peopleCount}</td>
                  <td className="act"><RowActions onEdit={() => setDlg({ kind: 'role', row: r })} onDelete={() => remove('role', r)} /></td>
                </tr>
              ))}
            </tbody></table>
        </section>

        <section className="panel">
          <div className="ph">People <button className="sm pri" onClick={() => setDlg({ kind: 'person', row: null })}>+ Person</button></div>
          <table className="grid"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th className="act" /></tr></thead>
            <tbody>
              {people.length === 0 && <tr><td colSpan={4} className="muted">None yet.</td></tr>}
              {people.map((p) => (
                <tr key={p.id}>
                  <td><span className="avatar">{p.name.split(' ').map((s) => s[0]).slice(0, 2).join('').toUpperCase()}</span>{p.name}</td><td className="muted">{p.email || ''}</td><td className="muted">{p.roleName || '—'}</td>
                  <td className="act"><RowActions onEdit={() => setDlg({ kind: 'person', row: p })} onDelete={() => remove('person', p)} /></td>
                </tr>
              ))}
            </tbody></table>
        </section>
      </div>

      {dlg?.kind === 'org' && <OrgDialog row={dlg.row} onClose={() => setDlg(null)} onSaved={() => { setDlg(null); load() }} />}
      {dlg?.kind === 'role' && <RoleDialog row={dlg.row} orgs={orgs} onClose={() => setDlg(null)} onSaved={() => { setDlg(null); load() }} />}
      {dlg?.kind === 'person' && <PersonDialog row={dlg.row} roles={roles} onClose={() => setDlg(null)} onSaved={() => { setDlg(null); load() }} />}
    </div>
  )
}

function useSave(fn, onSaved) {
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const save = async () => { setBusy(true); setError(null); try { await fn(); onSaved() } catch (e) { setError(e) } finally { setBusy(false) } }
  return { error, setError, busy, save }
}

function OrgDialog({ row, onClose, onSaved }) {
  const [name, setName] = useState(row?.name || '')
  const [description, setDescription] = useState(row?.description || '')
  const body = { name: name.trim(), description: description || null }
  const { error, setError, busy, save } = useSave(() => row ? api.updateOrganisation(row.id, body) : api.createOrganisation(body), onSaved)
  return (
    <Modal title={row ? 'Edit organisation' : 'New organisation'} onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="pri" disabled={busy || !name.trim()} onClick={save}>{row ? 'Save changes' : 'Create organisation'}</button></>}>
      <Notice error={error} onClose={() => setError(null)} />
      <div className="fld"><label>Name</label><input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div className="fld"><label>Description</label><textarea value={description} onChange={(e) => setDescription(e.target.value)} /></div>
    </Modal>
  )
}

function RoleDialog({ row, orgs, onClose, onSaved }) {
  const [name, setName] = useState(row?.name || '')
  const [responsibilities, setResponsibilities] = useState(row?.responsibilities || '')
  const [colour, setColour] = useState(row?.colour || '#2F6F9E')
  const [orgId, setOrgId] = useState(row?.organisationId || '')
  const [views, setViews] = useState(new Set(row?.views || ['portfolio', 'plan', 'assign', 'miles']))
  const body = { name: name.trim(), responsibilities: responsibilities || null, colour, organisationId: orgId ? +orgId : null, views: [...views] }
  const { error, setError, busy, save } = useSave(() => row ? api.updateRole(row.id, body) : api.createRole(body), onSaved)
  const toggle = (v) => { const n = new Set(views); n.has(v) ? n.delete(v) : n.add(v); setViews(n) }
  return (
    <Modal title={row ? 'Edit role' : 'New role'} onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="pri" disabled={busy || !name.trim()} onClick={save}>{row ? 'Save changes' : 'Create role'}</button></>}>
      <Notice error={error} onClose={() => setError(null)} />
      <div className="row2">
        <div className="fld"><label>Name</label><input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="fld"><label>Colour</label><input type="color" value={colour} onChange={(e) => setColour(e.target.value.toUpperCase())} /></div>
      </div>
      <div className="fld"><label>Organisation</label>
        <select value={orgId} onChange={(e) => setOrgId(e.target.value)}><option value="">—</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></div>
      <div className="fld"><label>Responsibilities</label><textarea value={responsibilities} onChange={(e) => setResponsibilities(e.target.value)} /></div>
      <div className="fld"><label>Can see</label>
        <div className="checks">{VIEWS.map(([v, l]) => <label key={v}><input type="checkbox" checked={views.has(v)} onChange={() => toggle(v)} /> {l}</label>)}</div>
        <span className="hint">Stored on the role for when authentication is added; nothing is hidden yet.</span>
      </div>
    </Modal>
  )
}

function PersonDialog({ row, roles, onClose, onSaved }) {
  const [name, setName] = useState(row?.name || '')
  const [email, setEmail] = useState(row?.email || '')
  const [roleId, setRoleId] = useState(row?.roleId || '')
  const body = { name: name.trim(), email: email || null, roleId: roleId ? +roleId : null }
  const { error, setError, busy, save } = useSave(() => row ? api.updatePerson(row.id, body) : api.createPerson(body), onSaved)
  return (
    <Modal title={row ? 'Edit person' : 'New person'} onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="pri" disabled={busy || !name.trim()} onClick={save}>{row ? 'Save changes' : 'Add person'}</button></>}>
      <Notice error={error} onClose={() => setError(null)} />
      <div className="fld"><label>Name</label><input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div className="fld"><label>Email</label><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
      <div className="fld"><label>Role</label>
        <select value={roleId} onChange={(e) => setRoleId(e.target.value)}><option value="">—</option>{roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select></div>
    </Modal>
  )
}
