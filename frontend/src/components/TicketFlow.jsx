import { useState } from 'react'
import { api } from '../api.js'

/*
  Where a ticket stands, and what this person may do about it.

  The buttons come from the ticket's own `actions` list, which the API works out
  from the same rules it enforces. So the screen never offers a move the server
  would refuse — the project manager sees "route", the team sees "resolve", the
  raiser sees "confirm" or "reopen", and everyone else sees where it sits.
*/
export const STAGES = [
  ['pm', 'With project manager'],
  ['team', 'With the team'],
  ['resolved', 'Resolved'],
  ['closed', 'Closed'],
]
export const STAGE_LABEL = Object.fromEntries(STAGES)

/** One cell for the ticket list: the stage, and who holds it. */
export function WithCell({ t }) {
  const who = t.stage === 'pm' ? (t.pmName || 'No project manager set')
    : t.stage === 'team' ? `${t.teamName}${t.assigneeName ? ` · ${t.assigneeName}` : ''}`
    : t.stage === 'resolved' ? 'Awaiting confirmation'
    : ''
  return (
    <div className="with-cell">
      <span className={`stage-pill st-${t.stage}`}>{STAGE_LABEL[t.stage]}</span>
      {who && <small>{who}</small>}
    </div>
  )
}

function Strip({ t }) {
  const order = STAGES.map(([k]) => k)
  const at = order.indexOf(t.stage)
  const sub = {
    pm: t.pmName || 'none named',
    team: t.teamName ? `${t.teamName}${t.assigneeName ? ` · ${t.assigneeName}` : ''}` : '',
    resolved: t.resolvedBy || '',
    closed: '',
  }
  return (
    <ol className="flow-strip" aria-label="Where this ticket is">
      {STAGES.map(([k, label], i) => (
        <li key={k} className={i < at ? 'done' : i === at ? 'now' : ''}>
          <b>{label}</b>
          {(i <= at && sub[k]) && <small>{sub[k]}</small>}
        </li>
      ))}
    </ol>
  )
}

export default function TicketFlow({ t, roles, people, onChanged, onError }) {
  const can = new Set(t.actions || [])
  const teams = (roles || []).filter((r) => !r.isCustomer && !r.is_customer)
  const [team, setTeam] = useState(t.teamRoleId || '')
  const [who, setWho] = useState('')
  const [note, setNote] = useState('')
  const [resolution, setResolution] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const inTeam = (people || []).filter((p) => String(p.roleId) === String(team))

  async function act(fn) {
    setBusy(true)
    try { onChanged(await fn()) } catch (e) { onError(e) } finally { setBusy(false) }
  }

  return (
    <div className="flow">
      <Strip t={t} />

      {t.stage === 'pm' && !t.pmId && (
        <div className="flow-note warn">
          This project has no project manager named, so an administrator routes its
          tickets. Set one as the project's owner to give them this queue.
        </div>
      )}

      {t.resolution && (
        <div className="flow-resolution">
          <div className="lbl">Resolution{t.resolvedBy ? ` · ${t.resolvedBy}` : ''}</div>
          <p>{t.resolution}</p>
        </div>
      )}

      {can.has('route') && (
        <div className="flow-act">
          <h4>{t.stage === 'team' ? 'Send it to another team' : 'Send this ticket to a team'}</h4>
          <div className="flow-row">
            <label>Team
              <select value={team} onChange={(e) => { setTeam(e.target.value); setWho('') }}>
                <option value="">— choose a team —</option>
                {teams.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </label>
            <label>Person <small>(optional)</small>
              <select value={who} onChange={(e) => setWho(e.target.value)} disabled={!team}>
                <option value="">Anyone in the team</option>
                {inTeam.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
          </div>
          <label className="flow-wide">Note to the team <small>(optional, goes on the thread)</small>
            <input value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder="What to look at first" />
          </label>
          <button type="button" className="pri" disabled={busy || !team}
                  onClick={() => act(() => api.routeTicket(t.id, {
                    team_role_id: Number(team), assignee_id: who ? Number(who) : null, note }))}>
            {t.stage === 'team' ? 'Re-route' : 'Send to team'}
          </button>
        </div>
      )}

      {can.has('resolve') && (
        <div className="flow-act">
          <h4>Record the resolution</h4>
          <textarea rows={3} value={resolution} onChange={(e) => setResolution(e.target.value)}
                    placeholder="What was wrong, and what was done. The raiser reads this to decide whether to close it." />
          <button type="button" className="pri" disabled={busy || resolution.trim().length < 10}
                  onClick={() => act(() => api.resolveTicket(t.id, resolution.trim()))}>
            Mark resolved
          </button>
        </div>
      )}

      {(can.has('close') || can.has('reopen')) && (
        <div className="flow-act">
          <h4>{t.stage === 'closed' ? 'Reopen this ticket' : 'Is it fixed?'}</h4>
          {can.has('close') && (
            <button type="button" className="pri" disabled={busy}
                    onClick={() => act(() => api.closeTicket(t.id))}>
              Yes — close the ticket
            </button>
          )}
          {can.has('reopen') && (
            <div className="flow-reopen">
              <input value={reason} onChange={(e) => setReason(e.target.value)}
                     placeholder="What is still wrong?" />
              <button type="button" disabled={busy || reason.trim().length < 5}
                      onClick={() => act(() => api.reopenTicket(t.id, reason.trim()))}>
                Not fixed — reopen
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
