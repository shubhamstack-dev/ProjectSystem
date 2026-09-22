import { useState } from 'react'
import { api } from '../api.js'

/**
 * Shown on first sign-in, and after an administrator resets a password.
 *
 * A password somebody else issued has been seen by at least one other person,
 * so it is not a secret. The API refuses everything but this until it is
 * replaced; this screen is the friendly face of that rule.
 */
export default function ChangePassword({ user, onDone, onSignOut }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const tooShort = next.length > 0 && next.length < 8
  const mismatch = again.length > 0 && next !== again
  const same = next.length > 0 && next === current

  async function save(e) {
    e.preventDefault()
    setErr('')
    if (next.length < 8) return setErr('Use at least 8 characters.')
    if (next !== again) return setErr('The two new passwords do not match.')
    if (next === current) return setErr('Choose something different from the one you were given.')
    setBusy(true)
    try {
      const r = await api.changePassword(current, next)
      onDone(r.user)
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }

  return (
    <div className="signin-wrap">
      <div className="signin-card">
        <div className="signin-head">
          <img className="logo-sq-img" src="/aequm-mark.png" alt="Aequm" width="40" height="40" />
          <div>
            <h1>Choose your own password</h1>
            <p>{user.display_name}{user.customer ? ` · ${user.customer.name}` : ''}</p>
          </div>
        </div>
        <div className="signin-note">
          You signed in with a password somebody else gave you. Replace it with one only you
          know before going any further.
        </div>
        {err && <div className="signin-err">{err}</div>}
        <form onSubmit={save} className="signin-form">
          <label htmlFor="cp-cur">The password you were given</label>
          <input id="cp-cur" type="password" autoComplete="current-password"
                 value={current} onChange={(e) => setCurrent(e.target.value)} />
          <label htmlFor="cp-new">New password</label>
          <input id="cp-new" type="password" autoComplete="new-password"
                 value={next} onChange={(e) => setNext(e.target.value)} />
          {tooShort && <small className="cp-hint">At least 8 characters.</small>}
          {same && <small className="cp-hint">That is the one you were given.</small>}
          <label htmlFor="cp-again">New password again</label>
          <input id="cp-again" type="password" autoComplete="new-password"
                 value={again} onChange={(e) => setAgain(e.target.value)} />
          {mismatch && <small className="cp-hint">These do not match yet.</small>}
          <button type="submit" disabled={busy || !current || next.length < 8 || next !== again || same}>
            {busy ? 'Saving…' : 'Save and continue'}
          </button>
        </form>
        <p className="signin-foot">
          <button type="button" className="linkish" onClick={onSignOut}>Sign out instead</button>
        </p>
      </div>
    </div>
  )
}
