import { useEffect, useState } from 'react'
import { api } from '../api.js'

/**
 * The customer master.
 *
 * A code and a name, then three assignments: which projects are delivered for
 * them, which customer roles are theirs, and which accounts belong to them.
 * The code is generated — a code somebody types is a code somebody mistypes,
 * and two spellings of one customer cannot be untangled once projects point at
 * both of them.
 */
export default function Customers() {
  const [rows, setRows] = useState([])
  const [projects, setProjects] = useState([])
  const [roles, setRoles] = useState([])
  const [guests, setGuests] = useState([])
  const [sel, setSel] = useState(null)
  const [nextCode, setNextCode] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  async function load(keepId) {
    try {
      const [cs, ps, rs] = await Promise.all([
        api.customers(), api.projects(), api.roles(),
      ])
      setRows(cs); setProjects(ps)
      setRoles(rs.filter(r => r.isCustomer || r.is_customer))
      const keep = keepId ?? sel?.id
      setSel(cs.find(x => x.id === keep) || cs[0] || null)
      api.nextCustomerCode().then(r => setNextCode(r.code)).catch(() => {})
      api.unassignedGuests().then(setGuests).catch(() => setGuests([]))
    } catch (e) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])   // eslint-disable-line

  async function create(e) {
    e.preventDefault()
    setErr(''); setMsg(''); setBusy(true)
    try {
      const made = await api.createCustomer(name.trim())
      setName('')
      setMsg(`${made.name} created as ${made.code}.`)
      await load(made.id)
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }

  async function assign(kind, id, on) {
    setErr(''); setMsg(''); setBusy(true)
    try {
      const current = new Set(
        kind === 'projects' ? sel.projects.map(x => x.id)
          : kind === 'roles' ? sel.roles.map(x => x.id)
            : sel.users.map(x => x.id))
      on ? current.add(id) : current.delete(id)
      const ids = [...current]
      const r = kind === 'projects' ? await api.setCustomerProjects(sel.id, ids)
        : kind === 'roles' ? await api.setCustomerRoles(sel.id, ids)
          : await api.setCustomerUsers(sel.id, ids)
      if (r?.moved?.length) setMsg(r.message)
      await load(sel.id)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function remove() {
    setErr(''); setMsg(''); setBusy(true)
    try { await api.deleteCustomer(sel.id); await load(null) }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const otherOwner = (p) =>
    rows.find(c => c.id !== sel?.id && c.projects.some(x => x.id === p.id))

  return (
    <div className="page">
      <div className="page-head">
        <h2>Customers</h2>
        <p>Who the work is delivered for. Assign their projects, their roles and
          their people; their users then see those projects and nothing else.</p>
      </div>

      {err && <div className="notice bad">{err}</div>}
      {msg && <div className="notice good">{msg}</div>}
      {guests.length > 0 && (
        <div className="notice warn">
          <b>{guests.length} customer account{guests.length === 1 ? ' has' : 's have'} no
            customer yet</b> — {guests.map(g => g.display_name).join(', ')}. Until one is
          assigned they sign in and see nothing at all.
        </div>
      )}

      <div className="proc-layout">
        <div className="proc-list">
          <h3>Customers</h3>
          {rows.length === 0 && <div className="empty">None yet.</div>}
          <ul>
            {rows.map(x => (
              <li key={x.id}>
                <button className={sel?.id === x.id ? 'on' : ''} onClick={() => setSel(x)}>
                  <b>{x.name}</b>
                  <small className="mono">{x.code}</small>
                  <small>{x.project_count} project{x.project_count === 1 ? '' : 's'} ·
                    {' '}{x.user_count} user{x.user_count === 1 ? '' : 's'}
                    {!x.active && ' · inactive'}</small>
                </button>
              </li>
            ))}
          </ul>

          <form className="proc-new" onSubmit={create}>
            <h3>New customer</h3>
            <label>Code</label>
            <input className="mono" value={nextCode} readOnly disabled />
            <div className="hint">Generated when you save.</div>
            <label htmlFor="cn">Name</label>
            <input id="cn" value={name} onChange={e => setName(e.target.value)} />
            <button type="submit" className="primary" disabled={busy || !name.trim()}>
              Create customer
            </button>
          </form>
        </div>

        <div className="proc-detail">
          {!sel ? <div className="empty">Create a customer to begin.</div> : (
            <>
              <div className="proc-title">
                <h3>{sel.name}</h3>
                <span className="pill mono">{sel.code}</span>
                {!sel.active && <span className="pill off">Inactive</span>}
                <button onClick={() => api.updateCustomer(sel.id, { active: !sel.active })
                  .then(() => load(sel.id)).catch(e => setErr(e.message))}
                        disabled={busy}>
                  {sel.active ? 'Mark inactive' : 'Reactivate'}
                </button>
                <button className="danger" onClick={remove} disabled={busy}>Delete</button>
              </div>

              <h4>Projects delivered for them</h4>
              <p className="muted">A project belongs to one customer. Assigning it here
                takes it off whoever had it before, and says so.</p>
              <div className="mod-picks">
                {projects.map(p => {
                  const on = sel.projects.some(x => x.id === p.id)
                  const owner = otherOwner(p)
                  return (
                    <label key={p.id} className={on ? 'on' : ''}>
                      <input type="checkbox" checked={on} disabled={busy}
                             onChange={e => assign('projects', p.id, e.target.checked)} />
                      <span>{p.code} · {p.name}
                        {owner && <small>currently {owner.name}</small>}</span>
                    </label>
                  )
                })}
                {projects.length === 0 && <div className="empty">No projects yet.</div>}
              </div>

              <h4 style={{ marginTop: 22 }}>Customer roles</h4>
              <p className="muted">Only roles marked as customer roles. A team role given
                to a customer would hand them the team's screens.</p>
              <div className="mod-picks">
                {roles.map(r => {
                  const on = sel.roles.some(x => x.id === r.id)
                  return (
                    <label key={r.id} className={on ? 'on' : ''}>
                      <input type="checkbox" checked={on} disabled={busy}
                             onChange={e => assign('roles', r.id, e.target.checked)} />
                      <span>{r.name}</span>
                    </label>
                  )
                })}
                {roles.length === 0 && (
                  <div className="empty">No customer roles defined. Add them on
                    Customer Roles.</div>
                )}
              </div>

              <h4 style={{ marginTop: 22 }}>Their people</h4>
              <p className="muted">Accounts from the directory marked as guests. An Aequm
                India account cannot be filed here.</p>
              <table className="grid">
                <thead><tr><th style={{ width: 34 }} /><th>Name</th><th>Address</th>
                  <th>Source</th></tr></thead>
                <tbody>
                  {[...sel.users, ...guests].map(u => {
                    const on = sel.users.some(x => x.id === u.id)
                    return (
                      <tr key={u.id}>
                        <td><input type="checkbox" checked={on} disabled={busy}
                                   onChange={e => assign('users', u.id, e.target.checked)} /></td>
                        <td><b>{u.display_name}</b></td>
                        <td className="mono">{u.email}</td>
                        <td>{u.source === 'entra' ? 'Microsoft' : 'Local'}</td>
                      </tr>
                    )
                  })}
                  {sel.users.length === 0 && guests.length === 0 && (
                    <tr><td colSpan={4} className="empty">
                      No customer accounts yet. Bring them in from the Directory first.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
