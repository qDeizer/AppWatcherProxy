import { startTransition, useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { ApplicationSummary, CertificateStatus, SessionSummary, Stats } from '../types'

const EMPTY_STATS: Stats = {
  session_count: 0,
  memory_bytes: 0,
  open_connections: 0,
  capture_state: 'stopped',
  capture_error: null,
  recording: false,
}

export function useInspector() {
  const [stats, setStats] = useState<Stats>(EMPTY_STATS)
  const [applications, setApplications] = useState<ApplicationSummary[]>([])
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [certificate, setCertificate] = useState<CertificateStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [controlError, setControlError] = useState<string | null>(null)
  const refreshing = useRef(false)

  const refresh = useCallback(async () => {
    if (refreshing.current) return
    refreshing.current = true
    try {
      const [nextStats, nextApplications, nextSessions, nextCertificate] = await Promise.all([
        api.stats(),
        api.applications(),
        api.sessions(),
        api.certificateStatus(),
      ])
      startTransition(() => {
        setStats(nextStats)
        setApplications(nextApplications)
        setSessions(nextSessions.items)
        setCertificate(nextCertificate)
        setError(null)
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Backend bağlantısı kurulamadı')
    } finally {
      refreshing.current = false
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 1500)
    return () => window.clearInterval(timer)
  }, [refresh])

  const runControl = useCallback(
    async (action: 'start' | 'stop' | 'clear') => {
      setControlError(null)
      try {
        await api[action]()
      } catch (reason) {
        setControlError(reason instanceof Error ? reason.message : 'İşlem başarısız')
      } finally {
        await refresh()
      }
    },
    [refresh],
  )

  return { stats, applications, sessions, certificate, error: controlError || error, loading, runControl, refresh }
}
