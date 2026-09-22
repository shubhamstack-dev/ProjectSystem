import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, Navigate } from 'react-router-dom'
import { api, getActingAs, setActingAs, getToken, setToken, onSignedOut, setCurrentUser } from './api.js'
import ChangePassword from './pages/ChangePassword.jsx'
import Portfolio from './pages/Portfolio.jsx'
import Plan from './pages/Plan.jsx'
import Team from './pages/Team.jsx'
import Assignments from './pages/Assignments.jsx'
import Milestones from './pages/Milestones.jsx'
import Audit from './pages/Audit.jsx'
import CustomerRoles from './pages/CustomerRoles.jsx'
import Phases from './pages/Phases.jsx'
import Tickets from './pages/Tickets.jsx'
import TicketModules from './pages/TicketModules.jsx'
import SignIn from './pages/SignIn.jsx'
import Directory from './pages/Directory.jsx'
import Processes from './pages/Processes.jsx'
import Customers from './pages/Customers.jsx'
import MailSettings from './pages/MailSettings.jsx'

const I = {
  portfolio: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>,
  plan: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 6h10M4 12h16M4 18h7"/><rect x="15" y="4" width="5" height="4" rx="1"/></svg>,
  miles: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3l9 9-9 9-9-9 9-9z"/></svg>,
  assign: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0"/><circle cx="17.5" cy="9" r="2.5"/><path d="M15.5 20a5 5 0 016-4.5"/></svg>,
  team: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 21V8l9-5 9 5v13"/><path d="M9 21v-6h6v6"/></svg>,
  audit: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>,
  customer: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5"/><circle cx="17" cy="17" r="4"/></svg>,
  phases: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 5h8v4H3zM7 10h10v4H7zM11 15h10v4H11z"/></svg>,
  tickets: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 8a2 2 0 002-2h12a2 2 0 002 2v2a2 2 0 000 4v2a2 2 0 00-2 2H6a2 2 0 00-2-2v-2a2 2 0 000-4V8z"/><path d="M13 6v2M13 11v2M13 16v2"/></svg>,
  cfg: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 00-2-1.2L14.2 3h-4l-.4 2.7a7 7 0 00-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 002 1.2l.4 2.7h4l.4-2.7a7 7 0 002-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"/></svg>,
}

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  // A token in sessionStorage may be expired or belong to a deleted account,
  // so it is only trusted once the API has confirmed it.
  useEffect(() => {
    onSignedOut(() => { setToken(''); setUser(null) })
    if (!getToken()) { setChecking(false); return }
    api.me().then(setUser).catch(() => setToken('')).finally(() => setChecking(false))
  }, [])

  // Whoever is signed in is who the audit trail records. The typed-in name is
  // gone: it was a label anybody could change to anybody else's.
  useEffect(() => {
    setCurrentUser(user)
    if (user) setActingAs(user.display_name || user.email)
  }, [user])

  function signOut() {
    setToken('')
    setUser(null)
    window.location.href = '/'
  }

  if (checking) return <div className="boot">Checking your session…</div>
  if (!user) return <SignIn onSignedIn={(u) => { setCurrentUser(u); setUser(u) }} />
  // A password somebody else issued has to be replaced before anything else.
  // The API holds the account to this too; the screen just says so kindly.
  if (user.must_change_password) {
    return <ChangePassword user={user} onDone={(u) => { setCurrentUser(u); setUser(u) }}
                           onSignOut={signOut} />
  }

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <img className="logo-img" src="/aequm-mark.png" alt="" width="30" height="30" />
          <span className="brand-txt"><b>Aequm</b><small>ProjectSystem</small></span>
        </div>
        <nav>
          {user.is_customer ? (
            /* A customer account sees what it can use and nothing else. The API
               refuses the rest; offering those screens would only lead to errors. */
            <NavLink to="/tickets">{I.tickets}<span>Tickets</span></NavLink>
          ) : (
            <>
              <NavLink to="/" end>{I.portfolio}<span>Portfolio</span></NavLink>
              <NavLink to="/plan">{I.plan}<span>Plan</span></NavLink>
              <NavLink to="/milestones">{I.miles}<span>Milestones</span></NavLink>
              <NavLink to="/assignments">{I.assign}<span>Assignments</span></NavLink>
              <NavLink to="/phases">{I.phases}<span>Phases</span></NavLink>
              <NavLink to="/tickets">{I.tickets}<span>Tickets</span></NavLink>
              <NavLink to="/processes">{I.cfg}<span>Processes</span></NavLink>
              <NavLink to="/ticket-setup">{I.cfg}<span>Ticket setup</span></NavLink>
              <div className="navsec">Roles</div>
              <NavLink to="/team">{I.team}<span>Team Roles</span></NavLink>
              <NavLink to="/customer-roles">{I.customer}<span>Customer Roles</span></NavLink>
              {user.is_admin && (
                <NavLink to="/customers">{I.customer}<span>Customers</span></NavLink>
              )}
              {user.is_admin && (
                <NavLink to="/directory">{I.team}<span>Directory</span></NavLink>
              )}
              {user.is_admin && (
                <NavLink to="/email">{I.audit}<span>Email</span></NavLink>
              )}
              <NavLink to="/audit">{I.audit}<span>Audit trail</span></NavLink>
            </>
          )}
        </nav>
        <div className="grow" />
        <div className="who">
          <div className="signed-in">
            <div className="avatar" aria-hidden="true">
              {(user.display_name || user.email).slice(0, 1).toUpperCase()}
            </div>
            <div className="sig-who">
              <b>{user.display_name}</b>
              <small>{user.email}</small>
              <small className="sig-tags">
                {user.is_admin && <span className="pill admin">Administrator</span>}
                <span className={`pill ${user.is_customer ? 'guest' : 'member'}`}>
                  {user.is_customer ? (user.customer?.name || 'Customer') : 'Aequm India'}
                </span>
                <span className="pill src">{user.source === 'entra' ? 'Microsoft' : 'Local'}</span>
              </small>
            </div>
          </div>
          <button className="signout" onClick={signOut}>Sign out</button>
          <div className="hint">Every change is recorded against this account.</div>
        </div>
      </aside>
      <main className="main">
        {user.is_customer && !user.customer && (
          <div className="notice warn" style={{ margin: '14px 22px 0' }}>
            No customer has been assigned to this account yet, so no projects are
            visible. Ask Aequm India to assign one.
          </div>
        )}
        {user.is_customer ? (
          <Routes>
            <Route path="/tickets" element={<Tickets />} />
            <Route path="*" element={<Navigate to="/tickets" />} />
          </Routes>
        ) : (
          <Routes>
            <Route path="/" element={<Portfolio />} />
            <Route path="/plan" element={<Plan />} />
            <Route path="/plan/:projectId" element={<Plan />} />
            <Route path="/milestones" element={<Milestones />} />
            <Route path="/assignments" element={<Assignments />} />
            <Route path="/team" element={<Team />} />
            <Route path="/customer-roles" element={<CustomerRoles />} />
            <Route path="/phases" element={<Phases />} />
            <Route path="/tickets" element={<Tickets />} />
            <Route path="/ticket-setup" element={<TicketModules />} />
            <Route path="/processes" element={<Processes />} />
            <Route path="/customers" element={
              user.is_admin ? <Customers /> : <Navigate to="/" />} />
            <Route path="/email" element={
            user.is_admin ? <MailSettings /> : <Navigate to="/" />} />
          <Route path="/directory" element={
              user.is_admin ? <Directory /> : <Navigate to="/" />} />
            <Route path="/auth/callback" element={<Navigate to="/" />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        )}
      </main>
    </div>
  )
}
