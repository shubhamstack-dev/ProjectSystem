import { useEffect, useState } from 'react'
import { api, setToken } from '../api.js'

const REDIRECT = `${window.location.origin}/auth/callback`

/**
 * The way in.
 *
 * Two routes on purpose. Microsoft is what Aequm India and its invited
 * customers use. The local form stays because a product that can only be
 * reached through a correctly configured tenant is a product that locks its
 * owner out the first time the tenant is misconfigured.
 */
export default function SignIn({ onSignedIn }) {
  const [opts, setOpts] = useState(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    api.authOptions().then(setOpts).catch(() =>
      setOpts({ local: true, microsoft: false, microsoft_reason: 'The API is not reachable' }))
  }, [])

  // Coming back from Microsoft: the code is in the query string.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    const code = q.get('code')
    const state = q.get('state')
    const oauthErr = q.get('error_description') || q.get('error')
    if (oauthErr) {
      setErr(oauthErr)
      window.history.replaceState({}, '', '/')
      return
    }
    if (!code || !state) return
    setBusy(true)
    setNotice('Finishing sign-in with Microsoft…')
    api.msCallback(code, state, REDIRECT)
      .then(r => {
        setToken(r.token)
        window.history.replaceState({}, '', '/')
        onSignedIn(r.user)
      })
      .catch(e => {
        setErr(e.message)
        window.history.replaceState({}, '', '/')
      })
      .finally(() => { setBusy(false); setNotice('') })
  }, [onSignedIn])

  async function signInWithMicrosoft() {
    setErr(''); setBusy(true)
    try {
      const { url } = await api.msStart(REDIRECT)
      window.location.href = url
    } catch (e) {
      setErr(e.message); setBusy(false)
    }
  }

  async function signInLocally(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const r = await api.login(email.trim(), password)
      setToken(r.token)
      onSignedIn(r.user)
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="signin-wrap">
      <div className="signin-card">
        <div className="signin-head">
          <span className="logo-sq" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5">
              <path d="M4 7h8M4 12h14M4 17h10" />
            </svg>
          </span>
          <div>
            <h1>ProjectSystem</h1>
            <p>Plans, phases and tickets for Aequm India</p>
          </div>
        </div>

        {notice && <div className="signin-note">{notice}</div>}
        {err && <div className="signin-err">{err}</div>}

        {opts?.microsoft ? (
          <button className="ms-btn" onClick={signInWithMicrosoft} disabled={busy}>
            <svg width="18" height="18" viewBox="0 0 23 23" aria-hidden="true">
              <rect x="1" y="1" width="10" height="10" fill="#F25022" />
              <rect x="12" y="1" width="10" height="10" fill="#7FBA00" />
              <rect x="1" y="12" width="10" height="10" fill="#00A4EF" />
              <rect x="12" y="12" width="10" height="10" fill="#FFB900" />
            </svg>
            <span>Sign in with Microsoft</span>
          </button>
        ) : opts ? (
          <div className="signin-off">
            Microsoft sign-in is not set up on this server.
            <span>{opts.microsoft_reason}</span>
          </div>
        ) : null}

        {opts?.microsoft && <div className="signin-or"><span>or</span></div>}

        <form onSubmit={signInLocally} className="signin-form">
          <label htmlFor="si-email">Email</label>
          <input id="si-email" type="email" autoComplete="username"
                 value={email} onChange={e => setEmail(e.target.value)} />
          <label htmlFor="si-pw">Password</label>
          <input id="si-pw" type="password" autoComplete="current-password"
                 value={password} onChange={e => setPassword(e.target.value)} />
          <button type="submit" disabled={busy || !email || !password}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="signin-foot">
          Your first sign-in creates nothing by itself. If you are new here, ask
          Aequm India to bring you in from the directory.
        </p>
      </div>
    </div>
  )
}
