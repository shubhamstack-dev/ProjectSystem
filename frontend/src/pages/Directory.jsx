import { useEffect, useState } from 'react'
import { api } from '../api.js'

/**
 * Fetching from Microsoft Entra ID and creating the people here.
 *
 * Fetch and import are two separate buttons on purpose. Reading the directory
 * changes nothing, so an administrator can look at what is there, and at who
 * is already in the system, before creating a single account.
 */
export default function Directory() {
  const [opts, setOpts] = useState(null)
  const [search, setSearch] = useState('')
  const [rows, setRows] = useState(null)
  const [summary, setSummary] = useState(null)
  const [picked, setPicked] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [history, setHistory] = useState([])

  useEffect(() => { api.authOptions().then(setOpts).catch(() => {}) }, [])
  useEffect(() => { api.directoryHistory().then(setHistory).catch(() => {}) }, [msg])

  async function fetchUsers(keepMessage) {
    setErr(''); if (!keepMessage) setMsg(''); setBusy(true)
    try {
      const r = await api.directoryUsers(search.trim() || undefined)
      setRows(r.users); setSummary(r)
      setPicked(new Set(r.users.filter(u => !u.already_here && u.enabled)
                                .map(u => u.oid)))
    } catch (e) { setErr(e.message); setRows(null) } finally { setBusy(false) }
  }

  async function importPicked() {
    setErr(''); setMsg(''); setBusy(true)
    try {
      const r = await api.directoryImport({
        oids: [...picked], search: search.trim() || undefined })
      setMsg(r.message + (r.notes?.length ? ` (${r.notes.length} note(s))` : ''))
      await fetchUsers(true)        // refresh the rows without wiping the confirmation
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  function toggle(oid) {
    setPicked(p => {
      const n = new Set(p)
      n.has(oid) ? n.delete(oid) : n.add(oid)
      return n
    })
  }

  if (opts && !opts.directory_import) {
    return (
      <div className="page">
        <h2>Directory</h2>
        <div className="notice warn">
          <b>Fetching users needs the application's own credentials.</b>
          <p>Set <code>ENTRA_TENANT_ID</code>, <code>ENTRA_CLIENT_ID</code> and{' '}
            <code>ENTRA_CLIENT_SECRET</code> in the backend <code>.env</code>, and grant{' '}
            <code>User.Read.All</code> as an <i>application</i> permission on the app
            registration with admin consent. Then restart the API.</p>
          <p>Sign-in through Microsoft needs only the first two; it is the directory
            read that needs the secret and the consent.</p>
        </div>
      </div>
    )
  }

  const guests = rows?.filter(r => r.user_type === 'Guest').length || 0

  return (
    <div className="page">
      <div className="page-head">
        <h2>Directory</h2>
        <p>Users from Microsoft Entra ID. Members are Aequm India staff; guests are
          customers invited into the tenant.</p>
      </div>

      <div className="dir-bar">
        <input placeholder="Filter by name or address, or leave empty for everyone"
               value={search} onChange={e => setSearch(e.target.value)}
               onKeyDown={e => { if (e.key === 'Enter') fetchUsers() }} />
        <button onClick={fetchUsers} disabled={busy}>
          {busy ? 'Working…' : 'Fetch from Microsoft'}
        </button>
        <button className="primary" onClick={importPicked}
                disabled={busy || picked.size === 0}>
          Create {picked.size || ''} user{picked.size === 1 ? '' : 's'} here
        </button>
      </div>

      {err && <div className="notice bad">{err}</div>}
      {msg && <div className="notice good">{msg}</div>}

      {summary && (
        <div className="dir-summary">
          <span><b>{summary.count}</b> in the directory</span>
          <span><b>{summary.members}</b> members</span>
          <span><b>{guests}</b> guests</span>
          <span><b>{summary.already_here}</b> already here</span>
        </div>
      )}

      {rows && (
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 34 }}>
                <input type="checkbox"
                       checked={rows.length > 0 && picked.size === rows.filter(r => r.enabled).length}
                       onChange={e => setPicked(e.target.checked
                         ? new Set(rows.filter(r => r.enabled).map(r => r.oid))
                         : new Set())} />
              </th>
              <th>Name</th><th>Address</th><th>Job title</th>
              <th>Type</th><th>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(u => (
              <tr key={u.oid} className={u.enabled ? '' : 'muted'}>
                <td><input type="checkbox" checked={picked.has(u.oid)}
                           disabled={!u.enabled}
                           onChange={() => toggle(u.oid)} /></td>
                <td><b>{u.display_name}</b></td>
                <td className="mono">{u.email || '—'}</td>
                <td>{u.job_title || '—'}</td>
                <td>
                  <span className={`pill ${u.user_type === 'Guest' ? 'guest' : 'member'}`}>
                    {u.user_type}
                  </span>
                </td>
                <td>
                  {!u.enabled ? <span className="pill off">Disabled there</span>
                    : u.already_here ? <span className="pill here">Already here</span>
                    : <span className="pill new">New</span>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="empty">Nothing matched that filter.</td></tr>
            )}
          </tbody>
        </table>
      )}

      {!rows && !err && (
        <div className="notice">
          Nothing has been read yet. Fetching only looks; it creates nobody until
          you choose who to bring in.
        </div>
      )}

      {history.length > 0 && (
        <>
          <h3 style={{ marginTop: 26 }}>Previous imports</h3>
          <table className="grid">
            <thead><tr><th>When</th><th>By</th><th>Fetched</th><th>Created</th>
              <th>Refreshed</th><th>Skipped</th></tr></thead>
            <tbody>
              {history.map(h => (
                <tr key={h.id}>
                  <td className="mono">{String(h.run_at_utc).replace('T', ' ').slice(0, 16)}</td>
                  <td>{h.run_by}</td>
                  <td className="mono">{h.fetched}</td>
                  <td className="mono">{h.created}</td>
                  <td className="mono">{h.updated}</td>
                  <td className="mono">{h.skipped}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
