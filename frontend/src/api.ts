import type { ApplicationSummary, CertificateStatus, SessionDetail, SessionPage, Stats } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `İstek başarısız (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  recordings: () => request<{items: {id: string; size: number; modified: string; password_required: boolean}[]; active: boolean; id: string | null; error: string | null}>('/api/recordings'),
  recordStart: (applications: string[]) => request('/api/recordings/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({applications})}),
  recordStop: () => request('/api/recordings/stop', {method: 'POST'}),
  recordOpen: (id: string, password: string | null = null) => request(`/api/recordings/${id}/open`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password})}),
  recordMitm: async (id: string, password: string | null = null) => {
    const response = await fetch(`/api/recordings/${id}/mitm`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password})})
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : `Dışa aktarım başarısız (${response.status})`)
    }
    return {blob: await response.blob(), exported: Number(response.headers.get('X-Exported-Sessions') ?? 0), skipped: Number(response.headers.get('X-Skipped-Sessions') ?? 0)}
  },
  recordExport: (applications: string[], query: string) => request('/api/recordings/export', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({applications, query})}),
  stats: () => request<Stats>('/api/stats'),
  certificateStatus: () => request<CertificateStatus>('/api/certificate/status'),
  applications: () => request<ApplicationSummary[]>('/api/applications'),
  sessions: (query = '') => {
    const params = new URLSearchParams({ limit: '1000' })
    if (query.trim()) params.set('q', query.trim())
    return request<SessionPage>(`/api/sessions?${params}`)
  },
  session: (id: string) => request<SessionDetail>(`/api/sessions/${encodeURIComponent(id)}`),
  start: () => request<{ state: string }>('/api/control/start', { method: 'POST' }),
  stop: () => request<{ state: string }>('/api/control/stop', { method: 'POST' }),
  clear: () => request<{ cleared: boolean }>('/api/control/clear', { method: 'POST' }),
}
