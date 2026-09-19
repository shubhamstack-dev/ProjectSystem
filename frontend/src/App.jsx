import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, Navigate } from 'react-router-dom'
import { getActingAs, setActingAs } from './api.js'
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
  const [who, setWho] = useState(getActingAs())
  useEffect(() => { setActingAs(who) }, [who])

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <span className="logo"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5"><path d="M4 7h8M4 12h14M4 17h10"/></svg></span>
          <span>ProjectSystem</span>
        </div>
        <nav>
          <NavLink to="/" end>{I.portfolio}<span>Portfolio</span></NavLink>
          <NavLink to="/plan">{I.plan}<span>Plan</span></NavLink>
          <NavLink to="/milestones">{I.miles}<span>Milestones</span></NavLink>
          <NavLink to="/assignments">{I.assign}<span>Assignments</span></NavLink>
          <NavLink to="/phases">{I.phases}<span>Phases</span></NavLink>
          <NavLink to="/tickets">{I.tickets}<span>Tickets</span></NavLink>
          <NavLink to="/ticket-setup">{I.cfg}<span>Ticket setup</span></NavLink>
          <div className="navsec">Roles</div>
          <NavLink to="/team">{I.team}<span>Team Roles</span></NavLink>
          <NavLink to="/customer-roles">{I.customer}<span>Customer Roles</span></NavLink>
          <NavLink to="/audit">{I.audit}<span>Audit trail</span></NavLink>
        </nav>
        <div className="grow" />
        <div className="who">
          <label htmlFor="who">Acting as</label>
          <input id="who" placeholder="Your name" value={who} onChange={(e) => setWho(e.target.value)} />
          <div className="hint">Recorded in the audit trail with every change.</div>
        </div>
      </aside>
      <main className="main">
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
          <Route path="/audit" element={<Audit />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  )
}
