import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Modal from '../components/Modal.jsx'
import Notice from '../components/Notice.jsx'
import { RowActions } from '../components/Icons.jsx'

/* Configuration: the modules/tools a ticket can be raised against. Each entry
   is flagged as living within SAP (FI, MM, SD ...) or outside SAP (a portal,
   middleware, custom app ...). Active modules show up in the ticket form. */

export default function TicketModules() {
  const [rows, setRows] = useState([])
  const [dlg, setDlg] = useState(null)   // { row: module|null }
  const [error, setError] = useState(null)

  const load = () => api.ticketModules().then(setRows).catch(setError)
  useEffect(() => { load() }, [])

  async function remove(m) {
    if (!confirm(`Delete module "${m.name}"?`)) return
    try { await api.deleteTicketModule(m.id); load() } catch (e) { setError(e) }
  }

  const sap = rows.filter((m) => m.moduleType === 'SAP')
  const non = rows.filter((m) => m.moduleType === 'NonSAP')

  const table = (list, title) => (
    <section className="panel">
      <h3 style={{ margin: '2px 0 8px' }}>{title}</h3>
      <table className="grid">
        <thead><tr><th>Name</th><th>Description</th><th>Status</th><th>Tickets</th><th /></tr></thead>
        <tbody>
          {list.length === 0 && <tr><td colSpan={5} className="muted">Nothing configured yet.</td></tr>}
          {list.map((m) => (
            <tr key={m.id}>
              <td><b>{m.name}</b></td>
              <td className="muted">{m.description || '—'}</td>
              <td><span className={`pill ${m.active ? 'ok' : 'plain'}`}>{m.active ? 'Active' : 'Inactive'}</span></td>
              <td style={{ textAlign: 'center' }}>{m.ticketCount}</td>
              <td><RowActions onEdit={() => setDlg({ row: m })} onDelete={() => remove(m)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )

  return (
    <div className="page">
      <h2>Ticket setup — modules</h2>
      <p className="lead">Configure every module a ticket can be raised against — within SAP or outside SAP.
        Active entries appear in the module dropdown when a ticket is created.</p>
      <Notice error={error} onClose={() => setError(null)} />

      <div style={{ marginBottom: 12 }}>
        <button className="sm pri" onClick={() => setDlg({ row: null })}>+ Module</button>
      </div>
      <div className="stack">
        {table(sap, 'Within SAP')}
        {table(non, 'Outside SAP')}
      </div>

      {dlg && <Editor row={dlg.row} onClose={() => setDlg(null)}
                      onSaved={() => { setDlg(null); load() }} onError={setError} />}
    </div>
  )
}

function Editor({ row, onClose, onSaved, onError }) {
  const [f, setF] = useState({
    name: row?.name || '', moduleType: row?.moduleType || 'SAP',
    description: row?.description || '', active: row ? row.active : true,
  })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  async function save() {
    setBusy(true)
    try {
      if (row) await api.updateTicketModule(row.id, f)
      else await api.createTicketModule(f)
      onSaved()
    } catch (e) { onError(e); onClose() } finally { setBusy(false) }
  }

  return (
    <Modal title={row ? `Edit "${row.name}"` : 'New module'} onClose={onClose} footer={
      <>
        <button onClick={onClose}>Cancel</button>
        <button className="pri" disabled={busy || !f.name.trim()} onClick={save}>{row ? 'Save' : 'Create'}</button>
      </>
    }>
      <div className="fld">
        <label>Name *</label>
        <input value={f.name} onChange={set('name')} placeholder="e.g. SAP FI, SAP MM, Vendor portal, Boomi middleware" />
      </div>
      <div className="fld">
        <label>Where does it live?</label>
        <select value={f.moduleType} onChange={set('moduleType')}>
          <option value="SAP">Within SAP</option>
          <option value="NonSAP">Outside SAP</option>
        </select>
      </div>
      <div className="fld">
        <label>Description</label>
        <textarea rows={3} value={f.description} onChange={set('description')}
                  placeholder="What this module covers, so people pick the right one." />
      </div>
      <div className="fld" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <input id="mact" type="checkbox" checked={f.active} onChange={set('active')} />
        <label htmlFor="mact" style={{ margin: 0 }}>Active (selectable on new tickets)</label>
      </div>
    </Modal>
  )
}
