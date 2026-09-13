import { ArrowDown, ArrowUp, Radio, Rows3 } from 'lucide-react'
import { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { SessionSummary } from '../types'

interface TrafficTableProps {
  sessions: SessionSummary[]
  selectedId: string | null
  onSelect: (session: SessionSummary) => void
  loading: boolean
}

const columns = ['Time', 'Application', 'Direction', 'Protocol', 'Host', 'Method/Event', 'Path', 'Status', 'Content Type', 'Sent', 'Received', 'Duration', 'Inspection']

export function TrafficTable({ sessions, selectedId, onSelect, loading }: TrafficTableProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({ count: sessions.length, getScrollElement: () => scrollRef.current, estimateSize: () => 34, overscan: 14 })
  return (
    <main className="traffic-panel panel">
      <div className="panel-heading traffic-heading"><div><Radio size={16} /><h2>Traffic</h2><span className="result-count">{sessions.length} sonuç</span></div><Rows3 size={16} /></div>
      <div className="traffic-columns">{columns.map((column) => <span key={column}>{column}</span>)}</div>
      <div className="traffic-scroll" ref={scrollRef}>
        {loading ? <LoadingRows /> : sessions.length ? (
          <div className="virtual-body" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const session = sessions[virtualRow.index]
              return <button
                className={`traffic-row ${selectedId === session.id ? 'selected' : ''}`}
                key={session.id}
                onClick={() => onSelect(session)}
                style={{ transform: `translateY(${virtualRow.start}px)` }}
              >
                <span className="mono">{new Date(session.time).toLocaleTimeString('tr-TR')}</span>
                <span title={session.application}>{session.application}</span>
                <span className="direction">{session.direction === 'up' ? <ArrowUp size={14} /> : <ArrowDown size={14} />}</span>
                <span className="mono">{session.protocol}</span><span title={session.host ?? ''}>{session.host || '—'}</span>
                <span className="mono">{session.method_event}</span><span title={session.path}>{session.path || '—'}</span>
                <span className="mono">{session.status ?? '—'}</span><span>{session.content_type || '—'}</span>
                <span className="mono">{formatBytes(session.sent)}</span><span className="mono">{formatBytes(session.received)}</span>
                <span className="mono">{formatDuration(session.duration_ms)}</span><span><InspectionBadge value={session.inspection} /></span>
              </button>
            })}
          </div>
        ) : <EmptyTraffic />}
      </div>
    </main>
  )
}

export function InspectionBadge({ value }: { value: SessionSummary['inspection'] }) {
  return <span className={`inspection inspection-${value.toLowerCase().replaceAll(' ', '-')}`}>{value}</span>
}

function formatBytes(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function formatDuration(duration: number | null) {
  if (duration == null) return '—'
  if (duration < 1000) return `${Math.round(duration)} ms`
  return `${(duration / 1000).toFixed(1)} s`
}

function EmptyTraffic() {
  return <div className="empty-traffic"><div className="empty-radar"><span /><span /><i /></div><h3>Yakalamaya hazır</h3><p>Başlat’a basınca sistem genelindeki dış bağlantılar burada gerçek zamanlı görünür.</p><dl><div><dt>01</dt><dd>CA sertifikasını kur</dd></div><div><dt>02</dt><dd>Capture’ı başlat</dd></div><div><dt>03</dt><dd>Bir uygulamada ağ isteği oluştur</dd></div></dl></div>
}

function LoadingRows() {
  return <div className="loading-rows">{Array.from({ length: 8 }, (_, index) => <span key={index} style={{ width: `${82 - index * 3}%` }} />)}</div>
}

