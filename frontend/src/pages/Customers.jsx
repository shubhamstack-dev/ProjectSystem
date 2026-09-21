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
  const [issued, setIssued] = useState(null)

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
              <p className="muted">Each of these can raise tickets on {sel.name}'s projects,
                follow the team's replies and reply back — and nothing else.</p>

              <AddPerson customer={sel} roles={roles} busy={busy}
                         onAdded={async (r) => { setIssued(r); setMsg(r.message); await load(sel.id) }}
                         onError={setErr} />
              {issued && issued.temporary_password && (
                <div className="issued">
                  <div>
                    <b>Password for {issued.user.display_name}</b>
                    <span>Shown once and not stored. Pass it on privately — they will be asked
                      to replace it when they first sign in.</span>
                  </div>
                  <code>{issued.temporary_password}</code>
                  <button type="button" onClick={() => {
                    navigator.clipboard?.writeText(issued.temporary_password)
                    setMsg('Copied. It will not be shown again.')
                  }}>Copy</button>
                  <button type="button" onClick={() => setIssued(null)}>Done</button>
                </div>
              )}

              <table className="grid" style={{ marginTop: 12 }}>
                <thead><tr><th style={{ width: 34 }} /><th>Name</th><th>Address</th>
                  <th>Role</th><th>Status</th><th style={{ width: 210 }} /></tr></thead>
                <tbody>
                  {[...sel.users, ...guests].map(u => {
                    const on = sel.users.some(x => x.id === u.id)
                    return (
                      <tr key={u.id} className={u.active === false ? 'muted' : ''}>
                        <td><input type="checkbox" checked={on} disabled={busy}
                                   title={on ? 'Belongs to this customer' : 'Not filed under a customer yet'}
                                   onChange={e => assign('users', u.id, e.target.checked)} /></td>
                        <td><b>{u.display_name}</b>
                          <small className="muted" style={{ display: 'block' }}>
                            {u.source === 'entra' ? 'Microsoft' : 'Local'}</small></td>
                        <td className="mono">{u.email}</td>
                        <td>{u.role || '—'}</td>
                        <td>{!on ? <span className="pill new">Not filed</span>
                          : u.active === false ? <span className="pill off">Deactivated</span>
                          : u.must_change_password ? <span className="pill new">Awaiting first sign-in</span>
                          : u.last_login_utc ? <span className="pill here">Active</span>
                          : <span className="pill member">Ready</span>}</td>
                        <td className="r" style={{ whiteSpace: 'nowrap' }}>
                          {on && u.source === 'local' && u.active !== false && (
                            <button type="button" disabled={busy} onClick={async () => {
                              setErr(''); setBusy(true)
                              try {
                                const r = await api.resetPassword(u.id)
                                setIssued({ user: { display_name: u.display_name },
                                            temporary_password: r.temporary_password })
                                await load(sel.id)
                              } catch (e) { setErr(e.message) } finally { setBusy(false) }
                            }}>Reset password</button>
                          )}
                          {on && (
                            <button type="button" disabled={busy} style={{ marginLeft: 6 }}
                                    onClick={async () => {
                              setErr(''); setBusy(true)
                              try { await api.updateAccount(u.id, { active: u.active === false });
                                    await load(sel.id) }
                              catch (e) { setErr(e.message) } finally { setBusy(false) }
                            }}>{u.active === false ? 'Reactivate' : 'Deactivate'}</button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                  {sel.users.length === 0 && guests.length === 0 && (
                    <tr><td colSpan={6} className="empty">
                      No one yet. Add a person above, or bring them in from the Directory.
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


/**
 * Add a person to this customer. A password is generated unless one is typed,
 * shown once, and has to be replaced at first sign-in.
 */
function AddPerson({ customer, roles, busy, onAdded, onError }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [roleId, setRoleId] = useState('')
  const [pw, setPw] = useState('')
  const [saving, setSaving] = useState(false)
  // this customer's own roles first, then the shared ones
  const mine = roles.filter(r => r.customerId === customer.id || r.customer_id === customer.id)
  const shared = roles.filter(r => !(r.customerId || r.customer_id))
  const ok = name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) &&
    (!pw || pw.length >= 8)

  if (!open) {
    return (
      <button type="button" className="primary" onClick={() => setOpen(true)}
              disabled={!customer.active}
              title={customer.active ? '' : 'Reactivate the customer first'}>
        Add a person
      </button>
    )
  }
  async function save(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const r = await api.addCustomerUser(customer.id, {
        display_name: name.trim(), email: email.trim(),
        role_id: roleId ? Number(roleId) : null, password: pw || null })
      setName(''); setEmail(''); setPw(''); setRoleId(''); setOpen(false)
      onAdded(r)
    } catch (e2) { onError(e2.message) } finally { setSaving(false) }
  }
  return (
    <form className="add-person" onSubmit={save}>
      <div className="row">
        <label>Name<input value={name} onChange={e => setName(e.target.value)} autoFocus /></label>
        <label>Work email<input type="email" value={email}
                                onChange={e => setEmail(e.target.value)} /></label>
        <label>Role
          <select value={roleId} onChange={e => setRoleId(e.target.value)}>
            <option value="">{mine.length ? mine[0].name + ' (default)' : 'Customer Contact (default)'}</option>
            {mine.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            {shared.length > 0 && <optgroup label="Shared by all customers">
              {shared.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            </optgroup>}
          </select></label>
        <label>Password <small className="muted">(optional)</small>
          <input type="text" value={pw} onChange={e => setPw(e.target.value)}
                 placeholder="Leave empty to generate one" autoComplete="off" /></label>
      </div>
      <div className="row-actions">
        <button type="submit" className="primary" disabled={busy || saving || !ok}>
          {saving ? 'Adding…' : 'Add to ' + customer.name}</button>
        <button type="button" onClick={() => setOpen(false)}>Cancel</button>
        <small className="muted">They will be asked to choose their own password on first sign-in.</small>
      </div>
    </form>
  )
}
