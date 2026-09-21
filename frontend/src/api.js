// One small wrapper around fetch. Every call goes to /api/... which Vite
// forwards to the Python backend (see vite.config.js).
//
// The X-Acting-As header is who the audit trail attributes changes to. It is a
// record, not a login. The value comes from the "Acting as" box in the top bar.

let actingAs = localStorage.getItem('actingAs') || ''

// The bearer token issued by /api/auth. Held in memory and mirrored to
// sessionStorage rather than localStorage: a token in localStorage outlives
// the browser being closed, which is exactly what a shared machine should not do.
let token = sessionStorage.getItem('ps.token') || ''
let onUnauthorised = null

export function setToken(t) {
  token = t || ''
  if (token) sessionStorage.setItem('ps.token', token)
  else sessionStorage.removeItem('ps.token')
}
export function getToken() { return token }
export function onSignedOut(fn) { onUnauthorised = fn }

function authHeaders() {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function guard(status) {
  // One expired token would otherwise surface as a different confusing error
  // on every screen at once.
  if (status === 401 && onUnauthorised) onUnauthorised()
}

export function setActingAs(name) {
  actingAs = name
  localStorage.setItem('actingAs', name)
}
export function getActingAs() {
  return actingAs
}

export class ApiError extends Error {
  constructor(status, message, blockers) {
    super(message)
    this.status = status
    this.blockers = blockers || []
  }
}

async function call(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(actingAs ? { 'X-Acting-As': actingAs } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 204) return null
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    guard(res.status)
    const message = data?.message || detailText(data) || res.statusText
    throw new ApiError(res.status, message, data?.blockers)
  }
  return data
}

/** FastAPI puts a plain refusal in detail and a validation list there too. */
function detailText(data) {
  const d = data?.detail
  if (!d) return null
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map(x => x.msg || JSON.stringify(x)).join('; ')
  return JSON.stringify(d)
}


// Multipart variant - used by tickets so documents can travel with the call.
async function callForm(method, url, fields, files) {
  const fd = new FormData()
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined && v !== null && v !== '') fd.append(k, v)
  }
  for (const f of files || []) fd.append('files', f)
  const res = await fetch(url, {
    method,
    headers: { ...authHeaders(), ...(actingAs ? { 'X-Acting-As': actingAs } : {}) },
    body: fd,
  })
  if (res.status === 204) return null
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    guard(res.status)
    const message = data?.message || detailText(data) || res.statusText
    throw new ApiError(res.status, message, data?.blockers)
  }
  return data
}

export const api = {
  // ---- sign-in and the directory
  authOptions: () => call('GET', '/api/auth/options'),
  login: (email, password) => call('POST', '/api/auth/login', { email, password }),
  me: () => call('GET', '/api/auth/me'),
  changePassword: (current, next) => call('POST', '/api/auth/password', { current, new: next }),
  msStart: (redirectUri) =>
    call('GET', `/api/auth/microsoft/start?redirect_uri=${encodeURIComponent(redirectUri)}`),
  msCallback: (code, state, redirectUri) =>
    call('POST', '/api/auth/microsoft/callback', { code, state, redirect_uri: redirectUri }),
  directoryUsers: (search) =>
    call('GET', `/api/auth/directory/users${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  directoryImport: (body) => call('POST', '/api/auth/directory/import', body || {}),
  directoryHistory: () => call('GET', '/api/auth/directory/history'),
  accounts: () => call('GET', '/api/auth/users'),
  createAccount: (body) => call('POST', '/api/auth/users', body),
  updateAccount: (id, body) => call('PUT', `/api/auth/users/${id}`, body),

  // ---- the customer master
  customers: () => call('GET', '/api/customers'),
  nextCustomerCode: () => call('GET', '/api/customers/next-code'),
  createCustomer: (name) => call('POST', '/api/customers', { name }),
  updateCustomer: (id, body) => call('PUT', `/api/customers/${id}`, body),
  deleteCustomer: (id) => call('DELETE', `/api/customers/${id}`),
  setCustomerProjects: (id, projectIds) =>
    call('PUT', `/api/customers/${id}/projects`, { project_ids: projectIds }),
  setCustomerRoles: (id, roleIds) =>
    call('PUT', `/api/customers/${id}/roles`, { role_ids: roleIds }),
  setCustomerUsers: (id, userIds) =>
    call('PUT', `/api/customers/${id}/users`, { user_ids: userIds }),
  unassignedGuests: () => call('GET', '/api/customers/unassigned'),

  // ---- processes and their steps
  processes: (moduleId) =>
    call('GET', `/api/processes${moduleId ? `?module_id=${moduleId}` : ''}`),
  createProcess: (body) => call('POST', '/api/processes', body),
  updateProcess: (id, body) => call('PUT', `/api/processes/${id}`, body),
  deleteProcess: (id) => call('DELETE', `/api/processes/${id}`),
  addStep: (pid, body) => call('POST', `/api/processes/${pid}/steps`, body),
  updateStep: (sid, body) => call('PUT', `/api/steps/${sid}`, body),
  deleteStep: (sid) => call('DELETE', `/api/steps/${sid}`),
  reorderSteps: (pid, stepIds) =>
    call('PUT', `/api/processes/${pid}/steps/order`, { step_ids: stepIds }),
  moduleProcesses: (mid) => call('GET', `/api/modules/${mid}/processes`),
  setModuleProcesses: (mid, processIds) =>
    call('PUT', `/api/modules/${mid}/processes`, { process_ids: processIds }),

  // projects
  projects: () => call('GET', '/api/projects'),
  project: (id) => call('GET', `/api/projects/${id}`),
  createProject: (p) => call('POST', '/api/projects', p),
  updateProject: (id, p) => call('PUT', `/api/projects/${id}`, p),
  deleteProject: (id) => call('DELETE', `/api/projects/${id}`),
  baseline: (id) => call('POST', `/api/projects/${id}/baseline`),
  // activities
  createActivity: (a) => call('POST', '/api/activities', a),
  updateActivity: (id, a) => call('PUT', `/api/activities/${id}`, a),
  deleteActivity: (id) => call('DELETE', `/api/activities/${id}`),
  moveActivity: (id, direction) => call('POST', `/api/activities/${id}/move`, { direction }),
  eligiblePredecessors: (id) => call('GET', `/api/activities/${id}/eligible-predecessors`),
  // team
  organisations: () => call('GET', '/api/team/organisations'),
  createOrganisation: (o) => call('POST', '/api/team/organisations', o),
  updateOrganisation: (id, o) => call('PUT', `/api/team/organisations/${id}`, o),
  deleteOrganisation: (id) => call('DELETE', `/api/team/organisations/${id}`),
  roles: () => call('GET', '/api/team/roles'),
  createRole: (r) => call('POST', '/api/team/roles', r),
  updateRole: (id, r) => call('PUT', `/api/team/roles/${id}`, r),
  deleteRole: (id) => call('DELETE', `/api/team/roles/${id}`),
  people: () => call('GET', '/api/team/people'),
  createPerson: (p) => call('POST', '/api/team/people', p),
  updatePerson: (id, p) => call('PUT', `/api/team/people/${id}`, p),
  deletePerson: (id) => call('DELETE', `/api/team/people/${id}`),
  workload: () => call('GET', '/api/team/workload'),
  // phases (roles & responsibilities per phase)
  phases: (projectId) => call('GET', `/api/projects/${projectId}/phases`),
  createPhase: (projectId, p) => call('POST', `/api/projects/${projectId}/phases`, p),
  updatePhase: (id, p) => call('PUT', `/api/phases/${id}`, p),
  deletePhase: (id) => call('DELETE', `/api/phases/${id}`),
  movePhase: (id, direction) => call('POST', `/api/phases/${id}/move`, { direction }),
  addPhaseAssignment: (phaseId, a) => call('POST', `/api/phases/${phaseId}/assignments`, a),
  deletePhaseAssignment: (id) => call('DELETE', `/api/phases/assignments/${id}`),
  // customer portal
  customerProjects: () => call('GET', '/api/customer/projects'),
  customerLines: (projectId) => call('GET', `/api/customer/projects/${projectId}/lines`),
  approveLine: (activityId, comment) => call('POST', `/api/customer/lines/${activityId}/approve`, { comment }),
  rejectLine: (activityId, comment) => call('POST', `/api/customer/lines/${activityId}/reject`, { comment }),
  // tickets (v1.2)
  ticketModules: () => call('GET', '/api/tickets/modules'),
  createTicketModule: (m) => call('POST', '/api/tickets/modules', m),
  updateTicketModule: (id, m) => call('PUT', `/api/tickets/modules/${id}`, m),
  deleteTicketModule: (id) => call('DELETE', `/api/tickets/modules/${id}`),
  tickets: (params) => call('GET', '/api/tickets?' + new URLSearchParams(params || {}).toString()),
  ticket: (id) => call('GET', `/api/tickets/${id}`),
  createTicket: (fields, files) => callForm('POST', '/api/tickets', fields, files),
  updateTicket: (id, t) => call('PUT', `/api/tickets/${id}`, t),
  deleteTicket: (id) => call('DELETE', `/api/tickets/${id}`),
  respondTicket: (id, body, files) => callForm('POST', `/api/tickets/${id}/responses`, { body }, files),
  attachmentUrl: (id) => `/api/tickets/attachments/${id}`,
  // audit
  audit: (params) => call('GET', '/api/audit?' + new URLSearchParams(params).toString()),
}

// ---- small helpers shared by pages ------------------------------------------
export const DEP_TYPES = ['FS', 'SS', 'FF', 'SF']
export const STATUS_NAMES = ['Active', 'On hold', 'Done']

export function fmt(d) {
  if (!d) return ''
  const [y, m, day] = d.split('-')
  return `${day} ${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m - 1]} ${y.slice(2)}`
}

export function signed(n) {
  if (n === null || n === undefined) return ''
  return n > 0 ? `+${n}` : `${n}`
}

export function today() {
  return new Date().toISOString().slice(0, 10)
}
