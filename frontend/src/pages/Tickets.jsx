import { useEffect, useRef, useState } from 'react'
import { api, getActingAs, getCurrentUser } from '../api.js'
import { FilePicker, UploadProgress, AttachmentGallery } from '../components/Uploads.jsx'
import Modal from '../components/Modal.jsx'
import Notice from '../components/Notice.jsx'
import { IcoTrash } from '../components/Icons.jsx'

/* Tickets: raised inside a project (optionally against a phase) for a
   configured module - within SAP or outside SAP. A ticket has a priority
   (High / Medium / Low), documents attached at creation or on any reply, and
   can be allocated to a person. The open ticket polls the server, so replies
   from the other side land on the thread automatically. */

export const PRIORITIES = ['High', 'Medium', 'Low']
export const STATUSES = ['Open', 'InProgress', 'Resolved', 'Closed']
const STATUS_LABEL = { Open: 'Open', InProgress: 'In progress', Resolved: 'Resolved', Closed: 'Closed' }
const PRIO_CLASS = { High: 'crit', Medium: 'warn', Low: 'acc' }
const STATUS_CLASS = { Open: 'pend', InProgress: 'acc', Resolved: 'ok', Closed: 'plain' }

function kb(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
function when(iso) {
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  return d.toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// ---- create-ticket dialog ---------------------------------------------------
function CreateDialog({ projects, modules, people, defaultProjectId, onClose, onSaved, onError }) {
  const [f, setF] = useState({
    projectId: defaultProjectId || '', phaseId: '', moduleId: '',
    processId: '', processStepId: '',
    title: '', description: '', priority: 'Medium', assigneeId: '',
  })
  const [phases, setPhases] = useState([])
  const [procs, setProcs] = useState([])
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  useEffect(() => {
    if (f.projectId) api.phases(f.projectId).then(setPhases).catch(onError)
    else setPhases([])
  }, [f.projectId])

  // Only the processes this module actually runs. Offering the rest would let
  // somebody raise a ticket against a step the module has nothing to do with,
  // which the API refuses anyway — better not to offer it at all.
  useEffect(() => {
    setF((prev) => ({ ...prev, processId: '', processStepId: '' }))
    if (f.moduleId) api.processes(f.moduleId).then(setProcs).catch(() => setProcs([]))
    else setProcs([])
  }, [f.moduleId])

  const [progress, setProgress] = useState(null)
  async function save() {
    setBusy(true)
    setProgress(files.length ? 0 : null)
    try {
      const t = await api.createTicket({
        project_id: f.projectId, phase_id: f.phaseId, module_id: f.moduleId,
        process_id: f.processId, process_step_id: f.processStepId,
        title: f.title, description: f.description, priority: f.priority,
        assignee_id: f.assigneeId,
      }, files, files.length ? setProgress : null)
      onSaved(t)
    } catch (e) { onError(e) } finally { setBusy(false); setProgress(null) }
  }

  const activeModules = modules.filter((m) => m.active)
  return (
    <Modal title="New ticket" onClose={onClose} footer={
      <>
        <button onClick={onClose}>Cancel</button>
        <button className="pri" disabled={busy || !f.projectId || !f.title.trim()} onClick={save}>
          {busy ? 'Creating…' : 'Create ticket'}
        </button>
      </>
    }>
      <div className="row2">
        <div className="fld">
          <label>Project *</label>
          <select value={f.projectId} onChange={set('projectId')}>
            <option value="">— choose —</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
          </select>
        </div>
        <div className="fld">
          <label>Phase</label>
          <select value={f.phaseId} onChange={set('phaseId')} disabled={!phases.length}>
            <option value="">— none —</option>
            {phases.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="fld">
          <label>Module / tool</label>
          <select value={f.moduleId} onChange={set('moduleId')}>
            <option value="">— none —</option>
            <optgroup label="Within SAP">
              {activeModules.filter((m) => m.moduleType === 'SAP').map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </optgroup>
            <optgroup label="Outside SAP">
              {activeModules.filter((m) => m.moduleType === 'NonSAP').map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </optgroup>
          </select>
        </div>
        <div className="fld">
          <label>Process</label>
          <select value={f.processId}
                  onChange={(e) => setF({ ...f, processId: e.target.value, processStepId: '' })}
                  disabled={!f.moduleId || !procs.length}>
            <option value="">— none —</option>
            {procs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {f.moduleId && !procs.length && (
            <div className="hint">No process is assigned to this module yet.</div>
          )}
          {!f.moduleId && <div className="hint">Choose a module first.</div>}
        </div>
        <div className="fld">
          <label>Process step</label>
          <select value={f.processStepId} onChange={set('processStepId')}
                  disabled={!f.processId}>
            <option value="">— none —</option>
            {(procs.find((p) => String(p.id) === String(f.processId))?.steps || [])
              .map((st) => <option key={st.id} value={st.id}>{st.sort_order}. {st.name}</option>)}
          </select>
        </div>
        <div className="fld">
          <label>Priority</label>
          <select value={f.priority} onChange={set('priority')}>
            {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
          </select>
        </div>
        {!getCurrentUser()?.is_customer && (
          <div className="fld">
            <label>Allocate to</label>
            <select value={f.assigneeId} onChange={set('assigneeId')}>
              <option value="">— unallocated —</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
        )}
      </div>
      <div className="fld">
        <label>Title *</label>
        <input value={f.title} onChange={set('title')} placeholder="Short summary of the issue or request" />
      </div>
      <div className="fld">
        <label>Description</label>
        <textarea rows={4} value={f.description} onChange={set('description')}
                  placeholder="What happened, where, steps to reproduce, expected outcome…" />
      </div>
      <FilePicker files={files} setFiles={setFiles}
                  label="Show the problem — screenshots, a screen recording, documents" />
      <UploadProgress progress={progress} />
    </Modal>
  )
}

// ---- ticket detail (thread) -------------------------------------------------
function TicketDetail({ id, people, modules, onClose, onChanged, onError }) {
  const [t, setT] = useState(null)
  const [reply, setReply] = useState('')
  const [replyProgress, setReplyProgress] = useState(null)
  const me = getCurrentUser()
  const isCustomer = !!me?.is_customer
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  const load = () => api.ticket(id).then(setT).catch(onError)
  useEffect(() => { load() }, [id])
  // Poll so responses from whoever the ticket is allocated to arrive by themselves.
  useEffect(() => {
    const h = setInterval(load, 10000)
    return () => clearInterval(h)
  }, [id])
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }) }, [t?.responses?.length])

  async function send() {
    if (!reply.trim()) return
    setBusy(true)
    try {
      setReplyProgress(files.length ? 0 : null)
      const updated = await api.respondTicket(id, reply, files,
                                              files.length ? setReplyProgress : null)
      setT(updated); setReply(''); setFiles([]); onChanged()
    } catch (e) { onError(e) } finally { setBusy(false); setReplyProgress(null) }
  }
  async function patch(p) {
    try { const updated = await api.updateTicket(id, p); setT(updated); onChanged() } catch (e) { onError(e) }
  }

  if (!t) return null
  const closed = t.status === 'Closed'
  return (
    <Modal title={`${t.number} — ${t.title}`} onClose={onClose}>
      <div className="tkt-head">
        <span className={`pill ${PRIO_CLASS[t.priority]}`}>{t.priority}</span>
        <span className={`pill ${STATUS_CLASS[t.status]}`}>{STATUS_LABEL[t.status]}</span>
        {t.moduleName && <span className="pill plain">{t.moduleName} · {t.moduleType === 'SAP' ? 'within SAP' : 'outside SAP'}</span>}
        {t.phaseName && <span className="pill plain">Phase: {t.phaseName}</span>}
        {t.processName && (
          <span className="pill proc">
            {t.processName}{t.processStepName ? ` · ${t.processStepName}` : ''}
          </span>
        )}
        <span className="muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
          {t.projectCode} · raised by {t.createdBy} · {when(t.createdAtUtc)}
        </span>
      </div>

      <div className="row3" style={{ margin: '10px 0' }}>
        <div className="fld">
          <label>Allocated to</label>
          {isCustomer ? <span className="ro">{t.assigneeName || 'Not yet allocated'}</span> :
          <select value={t.assigneeId || ''} onChange={(e) => patch({ assigneeId: e.target.value || null, moduleId: t.moduleId, phaseId: t.phaseId })}>
            <option value="">— unallocated —</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>}
        </div>
        <div className="fld">
          <label>Priority</label>
          {isCustomer ? <span className="ro">{t.priority}</span> :
          <select value={t.priority} onChange={(e) => patch({ priority: e.target.value, assigneeId: t.assigneeId, moduleId: t.moduleId, phaseId: t.phaseId })}>
            {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
          </select>}
        </div>
        <div className="fld">
          <label>Status</label>
          {isCustomer ? <span className="ro">{t.status === 'InProgress' ? 'In progress' : t.status}</span> :
          <select value={t.status} onChange={(e) => patch({ status: e.target.value, assigneeId: t.assigneeId, moduleId: t.moduleId, phaseId: t.phaseId })}>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>}
        </div>
      </div>

      {t.description && <div className="tkt-desc">{t.description}</div>}
      <AttachmentGallery list={t.attachments} />

      <div className="thread">
        {t.responses.length === 0 && <div className="muted" style={{ padding: '8px 0' }}>No responses yet.</div>}
        {t.responses.map((r) => {
          const mine = r.author === (getActingAs() || 'Unattributed')
          return (
            <div key={r.id} className={`msg ${mine ? 'mine' : ''}`}>
              <div className="msg-head"><b>{r.author}</b><span className="muted">{when(r.createdAtUtc)}</span></div>
              <div className="msg-body">{r.body}</div>
              <AttachmentGallery list={r.attachments} />
            </div>
          )
        })}
        <div ref={endRef} />
      </div>

      {closed ? (
        <div className="muted" style={{ marginTop: 8 }}>This ticket is closed. Set the status back to reopen it.</div>
      ) : (
        <div className="reply">
          <textarea rows={3} value={reply} onChange={(e) => setReply(e.target.value)}
                    placeholder="Write a response… it appears on the ticket the moment you send it." />
          <FilePicker files={files} setFiles={setFiles} label="Attach to your reply" />
          <UploadProgress progress={replyProgress} />
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="pri" disabled={busy || !reply.trim()} onClick={send}>
              {busy ? 'Sending…' : 'Send response'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ---- main page --------------------------------------------------------------
export default function Tickets() {
  const [projects, setProjects] = useState([])
  const [modules, setModules] = useState([])
  const [people, setPeople] = useState([])
  const [rows, setRows] = useState([])
  const [flt, setFlt] = useState({ projectId: '', status: '', priority: '', assigneeId: '' })
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [error, setError] = useState(null)

  const isCustomer = !!getCurrentUser()?.is_customer
  useEffect(() => {
    // A customer account is not given the team list — the gate refuses it,
    // and a customer has no business choosing who at Aequm picks the ticket up.
    Promise.all([api.projects(), api.ticketModules(),
                 isCustomer ? Promise.resolve([]) : api.people()])
      .then(([pr, m, pe]) => { setProjects(pr); setModules(m); setPeople(pe) })
      .catch(setError)
  }, [isCustomer])

  const load = () => {
    const p = {}
    if (flt.projectId) p.project_id = flt.projectId
    if (flt.status) p.status = flt.status
    if (flt.priority) p.priority = flt.priority
    if (flt.assigneeId) p.assignee_id = flt.assigneeId
    api.tickets(p).then(setRows).catch(setError)
  }
  useEffect(() => { load() }, [flt])
  useEffect(() => { const h = setInterval(load, 15000); return () => clearInterval(h) }, [flt])

  async function remove(t) {
    if (!confirm(`Delete ${t.number} "${t.title}" and its ${t.responseCount} response(s)?`)) return
    try { await api.deleteTicket(t.id); load() } catch (e) { setError(e) }
  }
  const set = (k) => (e) => setFlt({ ...flt, [k]: e.target.value })

  return (
    <div className="page">
      <h2>Tickets</h2>
      <p className="lead">Raise a ticket inside a project — against a phase and a configured module (within SAP
        or outside SAP) — attach documents, allocate it to someone, and follow the responses as they land.</p>
      <Notice error={error} onClose={() => setError(null)} />

      <div className="tkt-bar">
        <select value={flt.projectId} onChange={set('projectId')}>
          <option value="">All projects</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
        </select>
        <select value={flt.status} onChange={set('status')}>
          <option value="">Any status</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <select value={flt.priority} onChange={set('priority')}>
          <option value="">Any priority</option>
          {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
        </select>
        <select value={flt.assigneeId} onChange={set('assigneeId')}>
          <option value="">Anyone</option>
          {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <div className="grow" />
        <button className="pri" onClick={() => setCreating(true)}>+ New ticket</button>
      </div>

      <div className="panel">
      <table className="grid">
        <thead>
          <tr><th>No.</th><th>Title</th><th>Project</th><th>Phase</th><th>Process</th><th>Module</th>
              <th>Priority</th><th>Status</th><th>Allocated to</th><th>Replies</th><th>Updated</th><th /></tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={11} className="muted">No tickets match — raise the first one.</td></tr>}
          {rows.map((t) => (
            <tr key={t.id} className="rowlink" onClick={() => setOpenId(t.id)}>
              <td className="mono">{t.number}</td>
              <td>{t.title}</td>
              <td>{t.projectCode}</td>
              <td>{t.phaseName || '—'}</td>
              <td>{t.processName
                ? <>{t.processName}{t.processStepName &&
                    <div className="muted">{t.processStepName}</div>}</>
                : '—'}</td>
              <td>{t.moduleName ? <>{t.moduleName} <span className="muted">({t.moduleType === 'SAP' ? 'SAP' : 'non-SAP'})</span></> : '—'}</td>
              <td><span className={`pill ${PRIO_CLASS[t.priority]}`}>{t.priority}</span></td>
              <td><span className={`pill ${STATUS_CLASS[t.status]}`}>{STATUS_LABEL[t.status]}</span></td>
              <td>{t.assigneeName || <span className="muted">unallocated</span>}</td>
              <td style={{ textAlign: 'center' }}>{t.responseCount}</td>
              <td className="muted">{when(t.updatedAtUtc)}</td>
              <td onClick={(e) => e.stopPropagation()}>
                {!isCustomer && <button className="ib danger" title="Delete" onClick={() => remove(t)}><IcoTrash /></button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      {creating && (
        <CreateDialog projects={projects} modules={modules} people={people}
                      defaultProjectId={flt.projectId}
                      onClose={() => setCreating(false)}
                      onSaved={(t) => { setCreating(false); load(); setOpenId(t.id) }}
                      onError={setError} />
      )}
      {openId && (
        <TicketDetail id={openId} people={people} modules={modules}
                      onClose={() => setOpenId(null)} onChanged={load} onError={setError} />
      )}
    </div>
  )
}
