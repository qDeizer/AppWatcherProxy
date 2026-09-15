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
  const [recordBusy, setRecordBusy] = useState(false)
  const [recordActionError, setRecordActionError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query.trim())
  const [searchError, setSearchError] = useState<string | null>(null)
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
      setSearchError(null)
      return
    }
    let active = true
    const timeout = window.setTimeout(() => {
      void api.sessions(deferredQuery).then((page) => {
        if (active) {
          setSearchResults(page.items)
          setSearchError(null)
        }
      }).catch((reason) => {
        if (active) {
          setSearchResults([])
          setSearchError(reason instanceof Error ? reason.message : 'Arama tamamlanamadı')
        }
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

  const toggleRecording = async () => {
    if (recordBusy) return
    setRecordBusy(true)
    setRecordActionError(null)
    try {
      if (stats.recording) await api.recordStop()
      else await api.recordStart([...selectedApps])
    } catch (reason) {
      setRecordActionError(reason instanceof Error ? reason.message : 'Kayıt işlemi başarısız')
    } finally {
      await refresh(true)
      setRecordBusy(false)
    }
  }

  return <div className="app-shell">
    <TopBar stats={stats} query={query} onQueryChange={setQuery} onControl={(action) => void runControl(action)} onRecordToggle={() => void toggleRecording()} onRecordings={() => setRecordingOpen(true)} recordBusy={recordBusy} />
    {recordingOpen && <RecordingPanel applications={[...selectedApps]} query={query} onClose={() => setRecordingOpen(false)} onChanged={() => refresh(true)} />}
    {stats.recording && <div className="system-banner error-banner" role="status">● Kayıt açık · ⚠ Sensitive Data · {stats.recording_format === 'jsonl' ? 'Trafik şifresiz JSONL olarak diske yazılıyor.' : 'Eski sürüm şifreli kayıt yapıyor; şifresiz kayıt için uygulamayı yeniden başlatın.'}</div>}
    {stats.recording_format !== 'jsonl' && <div className="system-banner error-banner" role="alert">Şifresiz kayıt kodu hazır; çalışan eski backend’in değişmesi için Network Inspector’ı yeniden başlatın.</div>}
    {(stats.capture_error || stats.recording_error || stats.processing_error) && <div className="system-banner error-banner" role="alert">{stats.capture_error || stats.recording_error || stats.processing_error}</div>}
    {error || recordActionError || searchError ? <div className="system-banner error-banner" role="alert"><AlertTriangle size={16} /><strong>İşlem tamamlanamadı</strong><span>{recordActionError || searchError || error}</span></div> : null}
    {bannerVisible && certificate && !certificate.trusted ? <div className="system-banner"><AlertTriangle size={16} /><strong>CA sertifikası kurulmamış</strong><span>start.bat dosyasını yeniden çalıştırıp sertifika kurulumunu onaylayın.</span><button title="Bildirimi kapat" onClick={() => setBannerVisible(false)}><X size={15} /></button></div> : null}
    <div className="workspace-grid">
      <ApplicationPanel applications={applications} selected={selectedApps} onToggle={toggleApp} totalSessions={sessions.length} />
      <TrafficTable sessions={filtered} selectedId={selectedSessionId} onSelect={(session) => setSelectedSessionId(session.id)} loading={loading} />
      <DetailPanel session={selectedSession} certificate={certificate} query={deferredQuery} onClose={() => setSelectedSessionId(null)} />
    </div>
    <footer className="statusbar"><span><i className={`status-dot status-${stats.capture_state}`} />{stats.capture_state === 'running' ? 'Yerel capture etkin' : 'Ağ yapılandırması değiştirilmedi'}</span><span>RAM ring buffer · {stats.recording ? stats.recording_format === 'jsonl' ? 'Şifresiz disk kaydı açık' : 'Eski şifreli disk kaydı açık' : 'Disk kaydı kapalı'}</span><span>{window.location.host}</span></footer>
  </div>
}
