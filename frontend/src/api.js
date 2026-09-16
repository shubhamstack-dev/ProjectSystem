// One small wrapper around fetch. Every call goes to /api/... which Vite
// forwards to the Python backend (see vite.config.js).
//
// The X-Acting-As header is who the audit trail attributes changes to. It is a
// record, not a login. The value comes from the "Acting as" box in the top bar.

let actingAs = localStorage.getItem('actingAs') || ''

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
      ...(actingAs ? { 'X-Acting-As': actingAs } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 204) return null
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const message = data?.message || (data?.detail && JSON.stringify(data.detail)) || res.statusText
    throw new ApiError(res.status, message, data?.blockers)
  }
  return data
}

export const api = {
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
