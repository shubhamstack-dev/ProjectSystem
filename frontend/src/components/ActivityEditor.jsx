import { useEffect, useState } from 'react'
import Modal from './Modal.jsx'
import Notice from './Notice.jsx'
import { api, DEP_TYPES } from '../api.js'

const KIND = ['milestone', 'task', 'subtask']

/**
 * Props:
 *  projectId, level, afterId  -> creating a new row
 *  activity                   -> editing an existing row (from the project detail API)
 *  people, roles              -> pick lists
 *  onSaved(), onClose()
 */
export default function ActivityEditor({ projectId, level, afterId, activity, people, roles, onSaved, onClose }) {
  const isNew = !activity
  const lvl = isNew ? level : activity.level
  const locked = !isNew && activity.isLocked

  const [name, setName] = useState(activity?.name || '')
  const [manual, setManual] = useState(activity ? activity.mode === 1 : false)
  const [plannedStart, setPlannedStart] = useState(activity?.mode === 1 ? activity.plannedStart : '')
  const [plannedFinish, setPlannedFinish] = useState(activity?.mode === 1 ? activity.plannedFinish : '')
  const [duration, setDuration] = useState(activity?.duration ?? (lvl === 0 ? 0 : 1))
  const [targetDate, setTargetDate] = useState(activity?.targetDate || '')
  const [actualStart, setActualStart] = useState(activity?.actualStart || '')
  const [actualFinish, setActualFinish] = useState(activity?.actualFinish || '')
  const [percent, setPercent] = useState(activity?.percentComplete ?? 0)
  const [roleId, setRoleId] = useState(activity?.roleId || '')
  const [assignees, setAssignees] = useState(new Set((activity?.assignees || []).map((p) => p.id)))
  const [notes, setNotes] = useState(activity?.notes || '')
  const [deps, setDeps] = useState((activity?.dependencies || []).map((d) => ({ predecessorId: d.predecessorId, type: d.type, lag: d.lag, label: `${d.predecessorWbs} ${d.predecessorName}` })))
  const [eligible, setEligible] = useState([])
  const [pick, setPick] = useState({ predecessorId: '', type: 0, lag: 0 })
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (isNew) {
      // for a new row every existing activity in the project is a legal predecessor
      api.project(projectId).then((d) => setEligible(d.activities.map((a) => ({ id: a.id, wbs: a.wbs, name: a.name })))).catch(() => {})
    } else {
      api.eligiblePredecessors(activity.id).then(setEligible).catch(() => {})
    }
  }, [isNew, projectId, activity?.id])

  const available = eligible.filter((e) => !deps.some((d) => d.predecessorId === e.id))

  function addDep() {
    const e = eligible.find((x) => x.id === +pick.predecessorId)
    if (!e) return
    setDeps([...deps, { predecessorId: e.id, type: +pick.type, lag: +pick.lag || 0, label: `${e.wbs} ${e.name}` }])
    setPick({ predecessorId: '', type: 0, lag: 0 })
  }

  function toggle(id) {
    const next = new Set(assignees)
    next.has(id) ? next.delete(id) : next.add(id)
    setAssignees(next)
  }

  async function save() {
    setSaving(true); setError(null)
    try {
      if (isNew) {
        await api.createActivity({
          projectId, level: lvl, name, duration: +duration, afterActivityId: afterId || null,
          plannedStart: manual && plannedStart ? plannedStart : null,
          plannedFinish: manual && plannedFinish ? plannedFinish : null,
          targetDate: lvl === 0 && targetDate ? targetDate : null,
          notes: notes || null, roleId: roleId ? +roleId : null,
          assigneeIds: [...assignees],
          dependencies: deps.map(({ predecessorId, type, lag }) => ({ predecessorId, type, lag })),
        })
      } else {
        const body = {
          name,
          notes,
          percentComplete: +percent,
          assigneeIds: [...assignees],
          roleId: roleId ? +roleId : null, clearRole: !roleId,
          actualStart: actualStart || null, clearActualStart: !actualStart,
          actualFinish: actualFinish || null, clearActualFinish: !actualFinish,
        }
        if (!locked) {
          // plan fields are only sent when the plan is not locked, otherwise the server refuses the whole edit
          body.mode = manual ? 1 : 0
          if (manual && plannedStart) body.plannedStart = plannedStart
          if (manual && plannedFinish) body.plannedFinish = plannedFinish
          if (!manual || !plannedFinish) body.duration = +duration
          if (lvl === 0 && targetDate) body.targetDate = targetDate
          body.dependencies = deps.map(({ predecessorId, type, lag }) => ({ predecessorId, type, lag }))
        }
        await api.updateActivity(activity.id, body)
      }
      onSaved()
    } catch (e) {
      setError(e)
    } finally {
      setSaving(false)
    }
  }

  const title = isNew ? `New ${KIND[lvl]}` : `Edit ${KIND[lvl]} ${activity.wbs}`

  return (
    <Modal title={title} onClose={onClose} footer={
      <>
        <button onClick={onClose}>Cancel</button>
        <button className="pri" onClick={save} disabled={saving || !name.trim()}>{isNew ? `Create ${KIND[lvl]}` : 'Save changes'}</button>
      </>
    }>
      <Notice error={error} onClose={() => setError(null)} />
      {locked && <div className="locknote">Work has been recorded on this row (or beneath it), so planned dates, duration and links are locked. Actuals, progress, notes, role and assignees can still change.</div>}

      <div className="fld"><label>Name</label><input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></div>

      {!(isNew ? false : activity.isSummary) && (
        <>
          <div className="fld">
            <label>Scheduling</label>
            <div style={{ display: 'flex', gap: 16 }}>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="radio" disabled={locked} checked={!manual} onChange={() => setManual(false)} /> Auto (placed after its predecessors)</label>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="radio" disabled={locked} checked={manual} onChange={() => setManual(true)} /> Manual (typed dates)</label>
            </div>
          </div>
          {manual ? (
            <div className="row2">
              <div className="fld"><label>Planned start</label><input type="date" disabled={locked} value={plannedStart || ''} onChange={(e) => setPlannedStart(e.target.value)} /></div>
              <div className="fld"><label>Planned finish</label><input type="date" disabled={locked} value={plannedFinish || ''} onChange={(e) => setPlannedFinish(e.target.value)} /></div>
            </div>
          ) : (
            <div className="fld"><label>Duration (working days){lvl === 0 && <span className="hint"> — 0 makes a milestone marker</span>}</label>
              <input type="number" min="0" disabled={locked} value={duration} onChange={(e) => setDuration(e.target.value)} /></div>
          )}
        </>
      )}

      <div className="fld">
        <label>Depends on</label>
        <div className="deps">
          {deps.map((d, i) => (
            <div className="dep" key={i}>
              <span>{d.label}</span>
              <select disabled={locked} value={d.type} onChange={(e) => setDeps(deps.map((x, j) => j === i ? { ...x, type: +e.target.value } : x))}>
                {DEP_TYPES.map((t, k) => <option key={k} value={k}>{t}</option>)}
              </select>
              <input type="number" disabled={locked} value={d.lag} title="Lag in working days" onChange={(e) => setDeps(deps.map((x, j) => j === i ? { ...x, lag: +e.target.value } : x))} />
              <button className="sm" disabled={locked} onClick={() => setDeps(deps.filter((_, j) => j !== i))} aria-label="Remove link">×</button>
            </div>
          ))}
          {!locked && (
            <div className="dep add">
              <select value={pick.predecessorId} onChange={(e) => setPick({ ...pick, predecessorId: e.target.value })}>
                <option value="">{available.length ? 'Add a predecessor…' : 'Nothing eligible'}</option>
                {available.map((e) => <option key={e.id} value={e.id}>{e.wbs} {e.name}</option>)}
              </select>
              <select value={pick.type} onChange={(e) => setPick({ ...pick, type: e.target.value })}>{DEP_TYPES.map((t, k) => <option key={k} value={k}>{t}</option>)}</select>
              <input type="number" value={pick.lag} onChange={(e) => setPick({ ...pick, lag: e.target.value })} title="Lag" />
              <button className="sm" disabled={!pick.predecessorId} onClick={addDep}>+</button>
            </div>
          )}
        </div>
        <span className="hint">FS = finish-to-start, SS = start-to-start, FF = finish-to-finish, SF = start-to-finish. Lag is in working days and may be negative. Loops are refused.</span>
      </div>

      {lvl === 0 && (
        <div className="fld"><label>Milestone target date</label><input type="date" disabled={locked} value={targetDate} onChange={(e) => setTargetDate(e.target.value)} /></div>
      )}

      {!isNew && !activity.isSummary && (
        <div className="row3">
          <div className="fld"><label>Actual start</label><input type="date" value={actualStart} onChange={(e) => setActualStart(e.target.value)} /></div>
          <div className="fld"><label>Actual finish</label><input type="date" value={actualFinish} onChange={(e) => setActualFinish(e.target.value)} /></div>
          <div className="fld"><label>Progress %</label><input type="number" min="0" max="100" value={percent} disabled={!!actualFinish} onChange={(e) => setPercent(e.target.value)} /></div>
        </div>
      )}

      <div className="row2">
        <div className="fld"><label>Role</label>
          <select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
            <option value="">—</option>
            {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
      </div>

      <div className="fld">
        <label>Assigned to <span className="hint">(several people split the working days)</span></label>
        <div className="checks">
          {people.length === 0 && <span className="hint">No people yet — add them on the Team page.</span>}
          {people.map((p) => (
            <label key={p.id}><input type="checkbox" checked={assignees.has(p.id)} onChange={() => toggle(p.id)} /> {p.name}{p.roleName && <span className="muted"> · {p.roleName}</span>}</label>
          ))}
        </div>
      </div>

      <div className="fld"><label>Notes</label><textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
    </Modal>
  )
}
