import { useEffect, useState } from 'react'
import { api } from '../api.js'

/*
  Outgoing mail (SMTP) and incoming mail (IMAP) are two protocols, so two
  panels — even when they are the same mailbox. Passwords are never shown:
  the screen is told only whether one is set, and leaving the box empty keeps
  the stored one.
*/
const BLANK = {
  smtp_host: '', smtp_port: '587', smtp_security: 'starttls', smtp_user: '', smtp_password: '', smtp_auth: 'password',
  from_address: '', from_name: 'Aequm ProjectSystem', reply_to: '', app_url: '',
  imap_enabled: '0', imap_host: '', imap_port: '993', imap_user: '', imap_password: '', imap_auth: 'password',
  oauth_tenant_id: '', oauth_client_id: '', oauth_client_secret: '',
  imap_folder: 'INBOX', poll_minutes: '2',
}
const PRESETS = {
  'Microsoft 365': { smtp_host: 'smtp.office365.com', smtp_port: '587', smtp_security: 'starttls',
                     imap_host: 'outlook.office365.com', imap_port: '993' },
  'Google Workspace': { smtp_host: 'smtp.gmail.com', smtp_port: '587', smtp_security: 'starttls',
                        imap_host: 'imap.gmail.com', imap_port: '993' },
  'Zoho Mail (India)': { smtp_host: 'smtp.zoho.in', smtp_port: '465', smtp_security: 'ssl',
                         imap_host: 'imap.zoho.in', imap_port: '993' },
}

export default function MailSettings() {
  const [f, setF] = useState(BLANK)
  const [has, setHas] = useState({ smtp_password: false, imap_password: false, oauth_client_secret: false })
  const [ready, setReady] = useState({ sending_ready: false, receiving_ready: false })
  const [outbox, setOutbox] = useState([])
  const [inbound, setInbound] = useState([])
  const [testTo, setTestTo] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  function take(r) {
    const s = r.settings
    setHas({ smtp_password: !!s.smtp_password, imap_password: !!s.imap_password, oauth_client_secret: !!s.oauth_client_secret })
    setF({ ...BLANK, ...Object.fromEntries(Object.entries(s).map(([k, v]) =>
      [k, typeof v === 'boolean' ? '' : String(v ?? '')])) })
    setReady({ sending_ready: r.sending_ready, receiving_ready: r.receiving_ready })
  }
  const logs = () => Promise.all([api.mailOutbox(), api.mailInbound()])
    .then(([o, i]) => { setOutbox(o); setInbound(i) }).catch(() => {})
  useEffect(() => { api.mailSettings().then(take).catch((e) => setMsg({ bad: true, t: e.message })); logs() }, [])

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? (e.target.checked ? '1' : '0') : e.target.value })
  async function run(fn, ok) {
    setBusy(true); setMsg(null)
    try { const r = await fn(); setMsg({ t: ok(r) }); logs() }
    catch (e) { setMsg({ bad: true, t: e.message }) }
    finally { setBusy(false) }
  }
  const save = () => run(async () => { const r = await api.saveMailSettings(f); take(r); return r },
    () => 'Saved.')

  return (
    <div className="page">
      <div className="page-head">
        <h2>Email</h2>
        <p>Tickets email the project manager when raised, the team when routed, and the raiser when
          replied to or resolved. Replies to those emails come back onto the ticket.</p>
      </div>
      {msg && <div className={`notice ${msg.bad ? 'bad' : 'good'}`}>{msg.t}</div>}

      <div className="mail-presets">
        <span className="muted">Fill in the servers for</span>
        {Object.keys(PRESETS).map((k) => (
          <button key={k} type="button" onClick={() => setF({ ...f, ...PRESETS[k] })}>{k}</button>
        ))}
      </div>

      <div className="mail-grid">
        <section className="panel-lite">
          <h3>Sending — SMTP <span className={`pill ${ready.sending_ready ? 'here' : 'new'}`}>
            {ready.sending_ready ? 'Ready' : 'Not set up'}</span></h3>
          <div className="mail-fields">
            <label>Server<input value={f.smtp_host} onChange={set('smtp_host')} placeholder="smtp.office365.com" /></label>
            <label>Port<input value={f.smtp_port} onChange={set('smtp_port')} /></label>
            <label>Security
              <select value={f.smtp_security} onChange={set('smtp_security')}>
                <option value="starttls">STARTTLS (port 587)</option>
                <option value="ssl">SSL (port 465)</option>
                <option value="none">None (not recommended)</option>
              </select></label>
            <label>Authentication
              <select value={f.smtp_auth} onChange={set('smtp_auth')}>
                <option value="password">Password / app password</option>
                <option value="oauth">Microsoft 365 (OAuth, no password)</option>
              </select></label>
            <label>User<input value={f.smtp_user} onChange={set('smtp_user')} autoComplete="off" /></label>
            {f.smtp_auth !== 'oauth' && <label>Password
              <input type="password" value={f.smtp_password} onChange={set('smtp_password')}
                     autoComplete="new-password"
                     placeholder={has.smtp_password ? 'Set — leave empty to keep it' : 'App password'} /></label>}
            <label>From address<input value={f.from_address} onChange={set('from_address')} placeholder="tickets@aequm.in" /></label>
            <label>From name<input value={f.from_name} onChange={set('from_name')} /></label>
            <label>Reply-To <small>(the mailbox read below)</small>
              <input value={f.reply_to} onChange={set('reply_to')} placeholder="tickets@aequm.in" /></label>
            <label className="wide">Address of this system <small>(for links in emails)</small>
              <input value={f.app_url} onChange={set('app_url')} placeholder="https://nexdprojectsystems.com" /></label>
          </div>
          <div className="mail-actions">
            <input value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="Send a test to…" />
            <button type="button" disabled={busy} onClick={() => run(() => api.mailTest(testTo), (r) => r.message)}>
              Send test</button>
          </div>
        </section>

        <section className="panel-lite">
          <h3>Receiving — IMAP <span className={`pill ${ready.receiving_ready ? 'here' : 'new'}`}>
            {ready.receiving_ready ? 'Reading' : 'Off'}</span></h3>
          <label className="mail-check">
            <input type="checkbox" checked={f.imap_enabled === '1'} onChange={set('imap_enabled')} />
            Turn email replies into ticket responses
          </label>
          <div className="mail-fields">
            <label>Server<input value={f.imap_host} onChange={set('imap_host')} placeholder="outlook.office365.com" /></label>
            <label>Port<input value={f.imap_port} onChange={set('imap_port')} /></label>
            <label>Authentication
              <select value={f.imap_auth} onChange={set('imap_auth')}>
                <option value="password">Password / app password</option>
                <option value="oauth">Microsoft 365 (OAuth, no password)</option>
              </select></label>
            <label>Mailbox user<input value={f.imap_user} onChange={set('imap_user')} autoComplete="off" /></label>
            {f.imap_auth !== 'oauth' && <label>Password
              <input type="password" value={f.imap_password} onChange={set('imap_password')}
                     autoComplete="new-password"
                     placeholder={has.imap_password ? 'Set — leave empty to keep it' : 'App password'} /></label>}
            <label>Folder<input value={f.imap_folder} onChange={set('imap_folder')} /></label>
            <label>Check every (minutes)<input value={f.poll_minutes} onChange={set('poll_minutes')} /></label>
          </div>
          <p className="fine">A reply is accepted only from an active account allowed to see that
            ticket, with the [TCK-…] number still in the subject. Anything else is logged below and
            left alone.</p>
          <div className="mail-actions">
            <button type="button" disabled={busy} onClick={() => run(api.mailTestImap, (r) => r.message)}>
              Test the mailbox</button>
            <button type="button" disabled={busy || !ready.receiving_ready}
                    onClick={() => run(api.mailPoll, (r) => `Read ${r.read || 0}: ${r.posted || 0} posted, ${r.ignored || 0} ignored, ${r.refused || 0} refused.`)}>
              Check now</button>
          </div>
        </section>
      </div>

      {(f.smtp_auth === 'oauth' || f.imap_auth === 'oauth') && (
        <section className="mail-oauth" style={{ marginTop: 16 }}>
          <h3 style={{ margin: '0 0 6px' }}>Microsoft 365 app (OAuth)</h3>
          <p className="muted" style={{ margin: '0 0 10px' }}>
            Leave these empty to reuse the sign-in app from <code>.env</code> (ENTRA_TENANT_ID / ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET).
            The app needs Exchange Online application permissions <b>IMAP.AccessAsApp</b> and <b>SMTP.SendAsApp</b> with admin consent,
            and the mailbox must be granted to the app in Exchange &mdash; see SERVER-STEPS.md.
          </p>
          <div className="mail-fields">
            <label>Tenant ID<input value={f.oauth_tenant_id} onChange={set('oauth_tenant_id')} placeholder="from .env" autoComplete="off" /></label>
            <label>Client ID<input value={f.oauth_client_id} onChange={set('oauth_client_id')} placeholder="from .env" autoComplete="off" /></label>
            <label>Client secret
              <input type="password" value={f.oauth_client_secret} onChange={set('oauth_client_secret')} autoComplete="new-password"
                     placeholder={has.oauth_client_secret ? 'Set — leave empty to keep it' : 'from .env'} /></label>
          </div>
        </section>
      )}

      <div className="mail-save">
        <button type="button" className="primary" disabled={busy} onClick={save}>Save settings</button>
        <small className="muted">Passwords are stored encrypted with the server's SECRET_KEY. If that
          key changes, enter them again.</small>
      </div>

      <h3 style={{ marginTop: 26 }}>Sent and queued
        <button type="button" className="sm" style={{ marginLeft: 10 }} disabled={busy}
                onClick={() => run(api.mailSendNow, (r) => r.skipped ? 'Not set up yet.' : `${r.sent} sent, ${r.failed} failed.`)}>
          Send queued now</button></h3>
      <table className="grid">
        <thead><tr><th>To</th><th>Subject</th><th>Why</th><th>Status</th><th>Detail</th></tr></thead>
        <tbody>
          {outbox.length === 0 && <tr><td colSpan={5} className="empty">Nothing yet.</td></tr>}
          {outbox.map((r) => (
            <tr key={r.id}>
              <td className="mono">{r.to}</td><td>{r.subject}</td><td>{r.reason}</td>
              <td><span className={`pill ${r.status === 'sent' ? 'here' : r.status === 'failed' ? 'off' : 'new'}`}>
                {r.status}{r.attempts > 1 ? ` ×${r.attempts}` : ''}</span></td>
              <td className="fine">{r.last_error || ''}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 style={{ marginTop: 22 }}>Received</h3>
      <table className="grid">
        <thead><tr><th>From</th><th>Subject</th><th>Outcome</th><th>Note</th></tr></thead>
        <tbody>
          {inbound.length === 0 && <tr><td colSpan={4} className="empty">Nothing read yet.</td></tr>}
          {inbound.map((r) => (
            <tr key={r.id}>
              <td className="mono">{r.from}</td><td>{r.subject}</td>
              <td><span className={`pill ${r.outcome === 'posted' ? 'here' : r.outcome === 'refused' ? 'off' : 'member'}`}>
                {r.outcome}</span></td>
              <td className="fine">{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
