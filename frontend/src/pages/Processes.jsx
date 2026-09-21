import { useEffect, useState } from 'react'
import { api } from '../api.js'

/**
 * Processes, their steps, and which modules run them.
 *
 * A process is master data rather than a child of one module: period-end close
 * is one process that several modules run, and a copy per module drifts apart
 * the first time somebody edits one of them.
 */
export default function Processes() {
  const [procs, setProcs] = useState([])
  const [modules, setModules] = useState([])
  const [sel, setSel] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [descr, setDescr] = useState('')
  const [stepText, setStepText] = useState('')

  async function load(keepId) {
    try {
      const [p, m] = await Promise.all([api.processes(), api.ticketModules()])
      setProcs(p); setModules(m)
      const keep = keepId ?? sel?.id
      setSel(p.find(x => x.id === keep) || p[0] || null)
    } catch (e) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])   // eslint-disable-line

  async function createProcess(e) {
    e.preventDefault()
    setErr(''); setMsg(''); setBusy(true)
    try {
      const steps = stepText.split('\n').map(s => s.trim()).filter(Boolean)
                            .map((s, i) => ({ name: s, sort_order: i + 1 }))
      const p = await api.createProcess({
        name: name.trim(), code: code.trim() || null,
        description: descr.trim() || null, steps })
      setName(''); setCode(''); setDescr(''); setStepText('')
      setMsg(`${p.name} created with ${p.step_count} step${p.step_count === 1 ? '' : 's'}.`)
      await load(p.id)
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }

  async function addStep(stepName) {
    if (!sel || !stepName.trim()) return
    setErr(''); setBusy(true)
    try {
      await api.addStep(sel.id, { name: stepName.trim() })
      await load(sel.id)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function removeStep(sid) {
    setErr(''); setBusy(true)
    try { await api.deleteStep(sid); await load(sel.id) }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function move(idx, delta) {
    const ids = sel.steps.map(s => s.id)
    const j = idx + delta
    if (j < 0 || j >= ids.length) return
    ;[ids[idx], ids[j]] = [ids[j], ids[idx]]
    setBusy(true)
    try { await api.reorderSteps(sel.id, ids); await load(sel.id) }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function toggleModule(mid, on) {
    setErr(''); setMsg(''); setBusy(true)
    try {
      const current = await api.moduleProcesses(mid)
      const ids = new Set(current.map(p => p.id))
      on ? ids.add(sel.id) : ids.delete(sel.id)
      const r = await api.setModuleProcesses(mid, [...ids])
      if (r.kept?.length) setMsg(r.message)
      await load(sel.id)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function removeProcess() {
    if (!sel) return
    setErr(''); setMsg(''); setBusy(true)
    try { await api.deleteProcess(sel.id); await load(null) }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>Processes</h2>
        <p>A process and its ordered steps, then the modules that run it. Tickets
          can be raised against a step, so the work is located inside the process
          rather than only against the module.</p>
      </div>

      {err && <div className="notice bad">{err}</div>}
      {msg && <div className="notice good">{msg}</div>}

      <div className="proc-layout">
        <div className="proc-list">
          <h3>Defined</h3>
          {procs.length === 0 && <div className="empty">None yet.</div>}
          <ul>
            {procs.map(p => (
              <li key={p.id}>
                <button className={sel?.id === p.id ? 'on' : ''}
                        onClick={() => setSel(p)}>
                  <b>{p.name}</b>
                  <small>{p.step_count} step{p.step_count === 1 ? '' : 's'}
                    {p.module_ids.length
                      ? ` · ${p.module_ids.length} module${p.module_ids.length === 1 ? '' : 's'}`
                      : ' · not assigned'}</small>
                </button>
              </li>
            ))}
          </ul>

          <form className="proc-new" onSubmit={createProcess}>
            <h3>New process</h3>
            <label htmlFor="pn">Name</label>
            <input id="pn" value={name} onChange={e => setName(e.target.value)} />
            <label htmlFor="pc">Code</label>
            <input id="pc" value={code} onChange={e => setCode(e.target.value)}
                   placeholder="FI-CLOSE" />
            <label htmlFor="pd">Description</label>
            <input id="pd" value={descr} onChange={e => setDescr(e.target.value)} />
            <label htmlFor="ps">Steps, one per line</label>
            <textarea id="ps" rows={5} value={stepText}
                      onChange={e => setStepText(e.target.value)}
                      placeholder={'Freeze postings\nRun depreciation\nReconcile GR/IR'} />
            <button type="submit" className="primary" disabled={busy || !name.trim()}>
              Create process
            </button>
          </form>
        </div>

        <div className="proc-detail">
          {!sel ? (
            <div className="empty">Create a process to begin.</div>
          ) : (
            <>
              <div className="proc-title">
                <h3>{sel.name}</h3>
                {sel.code && <span className="pill">{sel.code}</span>}
                <button className="danger" onClick={removeProcess} disabled={busy}>
                  Delete
                </button>
              </div>
              {sel.description && <p className="muted">{sel.description}</p>}

              <h4>Steps</h4>
              <table className="grid">
                <thead><tr><th style={{ width: 40 }}>#</th><th>Step</th>
                  <th style={{ width: 130 }}>Order</th><th style={{ width: 70 }} /></tr></thead>
                <tbody>
                  {sel.steps.map((s, i) => (
                    <tr key={s.id}>
                      <td className="mono">{s.sort_order}</td>
                      <td><b>{s.name}</b>{s.description && <div className="muted">{s.description}</div>}</td>
                      <td>
                        <button onClick={() => move(i, -1)} disabled={busy || i === 0}>↑</button>
                        <button onClick={() => move(i, 1)}
                                disabled={busy || i === sel.steps.length - 1}>↓</button>
                      </td>
                      <td><button className="danger"
                                  onClick={() => removeStep(s.id)} disabled={busy}>Remove</button></td>
                    </tr>
                  ))}
                  {sel.steps.length === 0 && (
                    <tr><td colSpan={4} className="empty">No steps yet.</td></tr>
                  )}
                </tbody>
              </table>
              <AddStep onAdd={addStep} busy={busy} />

              <h4 style={{ marginTop: 22 }}>Modules that run this process</h4>
              <p className="muted">One process can serve several modules. A process
                already named on a ticket cannot be taken off that module.</p>
              <div className="mod-picks">
                {modules.map(m => {
                  const on = sel.module_ids.includes(m.id)
                  return (
                    <label key={m.id} className={on ? 'on' : ''}>
                      <input type="checkbox" checked={on} disabled={busy}
                             onChange={e => toggleModule(m.id, e.target.checked)} />
                      <span>{m.name}<small>{m.moduleType || m.module_type}</small></span>
                    </label>
                  )
                })}
                {modules.length === 0 && (
                  <div className="empty">No modules defined yet. Add them on Ticket Setup.</div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function AddStep({ onAdd, busy }) {
  const [v, setV] = useState('')
  return (
    <div className="add-step">
      <input value={v} placeholder="Add a step"
             onChange={e => setV(e.target.value)}
             onKeyDown={e => {
               if (e.key === 'Enter') { onAdd(v); setV('') }
             }} />
      <button disabled={busy || !v.trim()}
              onClick={() => { onAdd(v); setV('') }}>Add</button>
    </div>
  )
}
