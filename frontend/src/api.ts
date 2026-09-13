import type { ApplicationSummary, CertificateStatus, SessionDetail, SessionPage, Stats } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `İstek başarısız (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
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
