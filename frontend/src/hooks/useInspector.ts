import { startTransition, useCallback, useEffect, useState } from 'react'
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

  const refresh = useCallback(async () => {
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
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws`)
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'session_new' || message.type === 'session_complete') {
        setSessions((current) => [message.session, ...current.filter((item) => item.id !== message.session.id)].slice(0, 1000))
        void refresh()
      } else if (message.type === 'session_update') {
        setSessions((current) => {
          const index = current.findIndex((item) => item.id === message.session.id)
          if (index < 0) return [message.session, ...current].slice(0, 1000)
          const next = [...current]
          next[index] = message.session
          return next
        })
      } else if (message.type === 'sessions_cleared') {
        setSessions([])
        void refresh()
      } else if (message.type === 'status_change') {
        void refresh()
      }
    }
    return () => socket.close()
  }, [refresh])

  const runControl = useCallback(
    async (action: 'start' | 'stop' | 'clear') => {
      setError(null)
      try {
        await api[action]()
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'İşlem başarısız')
      } finally {
        await refresh()
      }
    },
    [refresh],
  )

  return { stats, applications, sessions, certificate, error, loading, runControl }
}
