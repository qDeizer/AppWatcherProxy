import { Circle, FolderOpen, Play, Search, Square, Trash2 } from 'lucide-react'
import { IconButton } from './IconButton'
import type { Stats } from '../types'

interface TopBarProps {
  stats: Stats
  query: string
  onQueryChange: (value: string) => void
  onControl: (action: 'start' | 'stop' | 'clear') => void
  onRecordToggle: () => void
  onRecordings: () => void
  recordBusy: boolean
}

function formatMemory(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function TopBar({ stats, query, onQueryChange, onControl, onRecordToggle, onRecordings, recordBusy }: TopBarProps) {
  const running = stats.capture_state === 'running' || stats.capture_state === 'starting'
  const busy = stats.capture_state === 'starting' || stats.capture_state === 'stopping'
  return (
    <header className="topbar">
      <div className="brand" aria-label="Network Inspector">
        <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
        <span>Network Inspector</span>
      </div>
      <div className="toolbar-actions">
        <IconButton
          icon={running ? <Square size={15} /> : <Play size={15} />}
          label={running ? 'Durdur' : 'Başlat'}
          variant="primary"
          disabled={busy}
          onClick={() => onControl(running ? 'stop' : 'start')}
        />
        <IconButton icon={stats.recording ? <Square size={15} /> : <Circle size={15} />} label={recordBusy ? 'İşleniyor…' : stats.recording ? 'Kaydı durdur' : 'Kayıt'} variant={stats.recording ? 'danger' : 'neutral'} disabled={recordBusy || (!stats.recording && stats.recording_format !== 'jsonl')} onClick={onRecordToggle} title={stats.recording ? 'Disk kaydını durdur' : stats.recording_format === 'jsonl' ? 'Tek tıkla şifresiz disk kaydını başlat' : 'Şifresiz kayıt için uygulamayı yeniden başlatın'} />
        <IconButton icon={<FolderOpen size={15} />} label="Kayıtlar" onClick={onRecordings} title="Kayıtları aç veya dışa aktar" />
        <IconButton icon={<Trash2 size={15} />} label="Temizle" onClick={() => onControl('clear')} />
      </div>
      <label className="searchbox">
        <Search size={16} aria-hidden="true" />
        <span className="sr-only">Arama</span>
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') onQueryChange('') }} placeholder="URL, header veya içerik ara" />
        {query ? <kbd>ESC</kbd> : <kbd>⌘ K</kbd>}
      </label>
      <div className="capture-summary">
        <div className={`capture-state state-${stats.capture_state}`}><span />{stateLabel(stats.capture_state)}</div>
        <Metric value={stats.session_count.toLocaleString('tr-TR')} label="Session" />
        <Metric value={stats.open_connections.toLocaleString('tr-TR')} label="Bağlantı" />
        <Metric value={formatMemory(stats.memory_bytes)} label="RAM" />
      </div>
    </header>
  )
}

function Metric({ value, label }: { value: string; label: string }) {
  return <div className="metric"><strong>{value}</strong><span>{label}</span></div>
}

function stateLabel(state: Stats['capture_state']) {
  const labels = { stopped: 'Capture durduruldu', starting: 'Başlatılıyor', running: 'Capture çalışıyor', stopping: 'Durduruluyor', error: 'Capture hatası' }
  return labels[state]
}
