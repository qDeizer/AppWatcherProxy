import { AlertTriangle, X } from 'lucide-react'
import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { ApplicationPanel } from './components/ApplicationPanel'
import { DetailPanel } from './components/DetailPanel'
import { TopBar } from './components/TopBar'
import { TrafficTable } from './components/TrafficTable'
import { RecordingPanel } from './components/RecordingPanel'
import { useInspector } from './hooks/useInspector'
import type { SessionSummary } from './types'

export default function App() {
  const { stats, applications, sessions, certificate, error, loading, runControl, refresh } = useInspector()
  const [recordingOpen, setRecordingOpen] = useState(false)
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query.trim().toLowerCase())
  const [searchResults, setSearchResults] = useState<SessionSummary[] | null>(null)
  const [selectedApps, setSelectedApps] = useState<Set<string>>(() => {
    const saved = new URLSearchParams(window.location.search).get('apps')
    return new Set(saved ? saved.split(',').filter(Boolean) : [])
  })
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [bannerVisible, setBannerVisible] = useState(true)

  useEffect(() => {
    const closeDrawer = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedSessionId(null)
    }
    window.addEventListener('keydown', closeDrawer)
    return () => window.removeEventListener('keydown', closeDrawer)
  }, [])

  useEffect(() => {
    if (!deferredQuery) {
      setSearchResults(null)
      return
    }
    let active = true
    const timeout = window.setTimeout(() => {
      void api.sessions(deferredQuery).then((page) => {
        if (active) setSearchResults(page.items)
      }).catch(() => {
        if (active) setSearchResults([])
      })
    }, 180)
    return () => {
      active = false
      window.clearTimeout(timeout)
    }
  }, [deferredQuery, sessions])

  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) ?? searchResults?.find((session) => session.id === selectedSessionId) ?? null,
    [searchResults, selectedSessionId, sessions],
  )

  const filtered = useMemo(() => (searchResults ?? sessions).filter((session) => {
    if (selectedApps.size && !selectedApps.has(session.application)) return false
    return true
  }), [searchResults, selectedApps, sessions])

  const toggleApp = (name: string) => setSelectedApps((current) => {
    const next = new Set(current)
    if (next.has(name)) {
      next.delete(name)
    } else {
      next.add(name)
    }
    const params = new URLSearchParams(window.location.search)
    if (next.size) {
      params.set('apps', [...next].join(','))
    } else {
      params.delete('apps')
    }
    window.history.replaceState(null, '', `${window.location.pathname}${params.size ? `?${params}` : ''}`)
    return next
  })

  return <div className="app-shell">
    <TopBar stats={stats} query={query} onQueryChange={setQuery} onControl={(action) => void runControl(action)} onRecording={() => setRecordingOpen(true)} />
    {recordingOpen && <RecordingPanel applications={[...selectedApps]} query={query} onClose={() => setRecordingOpen(false)} onChanged={refresh} />}
    {stats.recording && <div className="system-banner error-banner" role="status">● Kayıt açık · ⚠ Sensitive Data · Trafik şifreli olarak diske yazılıyor.</div>}
    {(stats.capture_error || stats.recording_error || stats.processing_error) && <div className="system-banner error-banner" role="alert">{stats.capture_error || stats.recording_error || stats.processing_error}</div>}
    {error ? <div className="system-banner error-banner" role="alert"><AlertTriangle size={16} /><strong>İşlem tamamlanamadı</strong><span>{error}</span></div> : null}
    {bannerVisible && certificate && !certificate.trusted ? <div className="system-banner"><AlertTriangle size={16} /><strong>CA sertifikası kurulmamış</strong><span>start.bat dosyasını yeniden çalıştırıp sertifika kurulumunu onaylayın.</span><button title="Bildirimi kapat" onClick={() => setBannerVisible(false)}><X size={15} /></button></div> : null}
    <div className="workspace-grid">
      <ApplicationPanel applications={applications} selected={selectedApps} onToggle={toggleApp} totalSessions={sessions.length} />
      <TrafficTable sessions={filtered} selectedId={selectedSessionId} onSelect={(session) => setSelectedSessionId(session.id)} loading={loading} />
      <DetailPanel session={selectedSession} certificate={certificate} query={deferredQuery} onClose={() => setSelectedSessionId(null)} />
    </div>
    <footer className="statusbar"><span><i className={`status-dot status-${stats.capture_state}`} />{stats.capture_state === 'running' ? 'Yerel capture etkin' : 'Ağ yapılandırması değiştirilmedi'}</span><span>RAM ring buffer · {stats.recording ? 'Şifreli disk kaydı açık' : 'Disk kaydı kapalı'}</span><span>{window.location.host}</span></footer>
  </div>
}
