import { AlertTriangle, Info, LockKeyhole, ShieldCheck, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { CertificateStatus, Header, Payload, SessionDetail, SessionSummary } from '../types'
import { InspectionBadge } from './TrafficTable'

const tabs = ['Overview', 'Request', 'Response', 'Stream', 'Connection', 'Raw', 'Hex'] as const
const BODY_TEXT_LIMIT = 256 * 1024
const HEX_LIMIT = 64 * 1024

interface DetailPanelProps {
  session: SessionSummary | null
  certificate: CertificateStatus | null
  query: string
  onClose: () => void
}

export function DetailPanel({ session, certificate, query, onClose }: DetailPanelProps) {
  const [tab, setTab] = useState<(typeof tabs)[number]>('Overview')
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sessionId = session?.id ?? null
  const sessionSent = session?.sent ?? 0
  const sessionReceived = session?.received ?? 0
  const sessionDuration = session?.duration_ms ?? null
  const sessionStreaming = session?.is_streaming ?? false

  useEffect(() => {
    if (!sessionId) {
      setDetail(null)
      setError(null)
      return
    }
    let active = true
    setLoading(true)
    const timeout = window.setTimeout(() => {
      void api.session(sessionId).then((value) => {
        if (active) {
          setDetail(value)
          setError(null)
        }
      }).catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Detay alınamadı')
      }).finally(() => {
        if (active) setLoading(false)
      })
    }, sessionStreaming ? 100 : 0)
    return () => {
      active = false
      window.clearTimeout(timeout)
    }
  }, [sessionId, sessionSent, sessionReceived, sessionDuration, sessionStreaming])

  return (
    <aside className={`detail-panel panel ${session ? 'detail-active' : 'detail-empty'}`}>
      <div className="panel-heading"><div><Info size={16} /><h2>Detail</h2></div>{session ? <button className="icon-only" onClick={onClose} aria-label="Detayı kapat"><X size={16} /></button> : null}</div>
      <div className="tabs" role="tablist">{tabs.map((item) => <button key={item} role="tab" aria-selected={tab === item} onClick={() => setTab(item)} disabled={!session && item !== 'Overview'}>{item}</button>)}</div>
      {!session ? <SetupGuide certificate={certificate} /> : error ? <DetailMessage title="Detay yüklenemedi" message={error} error /> : loading && !detail ? <DetailMessage title="Session yükleniyor" message="Request ve response verileri hazırlanıyor." /> : detail ? <SessionDetails summary={session} detail={detail} tab={tab} query={query} /> : null}
    </aside>
  )
}

function SessionDetails({ summary, detail, tab, query }: { summary: SessionSummary; detail: SessionDetail; tab: string; query: string }) {
  if (tab === 'Request') return <RequestView detail={detail} query={query} />
  if (tab === 'Response') return <ResponseView detail={detail} query={query} />
  if (tab === 'Stream') return <StreamView detail={detail} query={query} />
  if (tab === 'Connection') return <ConnectionView detail={detail} />
  if (tab === 'Raw') return <RawView detail={detail} query={query} />
  if (tab === 'Hex') return <HexView detail={detail} />
  return <OverviewView summary={summary} detail={detail} />
}

function OverviewView({ summary, detail }: { summary: SessionSummary; detail: SessionDetail }) {
  return <div className="detail-content"><section><h3>General</h3><DataRow label="Time" value={new Date(summary.time).toLocaleString('tr-TR')} /><DataRow label="Application" value={`${summary.application}${summary.pid ? ` (PID ${summary.pid})` : ''}`} /><DataRow label="Executable" value={detail.application.executable_path ?? detail.process.executable_path ?? '—'} /><DataRow label="Protocol" value={summary.protocol} /><DataRow label="Host" value={summary.host ?? '—'} /><DataRow label="Method/Event" value={summary.method_event} /><DataRow label="Path" value={summary.path || '—'} /><DataRow label="Status" value={summary.status?.toString() ?? 'Bekleniyor'} /><DataRow label="Sent / Received" value={`${formatBytes(summary.sent)} / ${formatBytes(summary.received)}`} /><DataRow label="Duration" value={formatDuration(summary.duration_ms)} /><div className="data-row"><span>Inspection</span><InspectionBadge value={summary.inspection} /></div></section>{summary.inspection_reason ? <section><h3>Visibility</h3><p className="inspection-note">{summary.inspection_reason}</p></section> : null}{detail.error ? <section><h3>Error</h3><p className="inspection-note error-text">{detail.error}</p></section> : null}</div>
}

function RequestView({ detail, query }: { detail: SessionDetail; query: string }) {
  const request = detail.request
  if (!request) return <DetailMessage title="Request bulunamadı" message="Bu session için HTTP request verisi yok." />
  const url = `${request.scheme}://${request.host}${defaultPort(request.scheme, request.port) ? '' : `:${request.port}`}${request.path}`
  return <div className="detail-content"><section><h3>Request</h3><DataRow label="Method" value={request.method} /><DataRow label="URL" value={url} /></section><PairSection title="Query parameters" values={request.query_params} empty="Query parametresi yok." /><HeaderSection title="Headers" headers={request.headers} /><PairSection title="Cookies" values={request.cookies} empty="Cookie yok." /><BodySection payload={request.body} query={query} /></div>
}

function ResponseView({ detail, query }: { detail: SessionDetail; query: string }) {
  const response = detail.response
  if (!response) return <DetailMessage title="Response bekleniyor" message="İstek yakalandı; karşı taraftan yanıt henüz tamamlanmadı." />
  return <div className="detail-content"><section><h3>Response</h3><DataRow label="Status" value={`${response.status_code} ${response.reason}`.trim()} /><DataRow label="Total" value={formatDuration(response.total_ms)} /></section><HeaderSection title="Headers" headers={response.headers} /><PairSection title="Set-Cookie" values={response.set_cookies.map((value) => ['set-cookie', value])} empty="Set-Cookie yok." /><BodySection payload={response.body} query={query} /></div>
}

function StreamView({ detail, query }: { detail: SessionDetail; query: string }) {
  const stream = detail.stream
  if (!stream) return <DetailMessage title="Akış verisi yok" message="Bu session normal HTTP request/response olarak tamamlandı." />
  return <div className="detail-content"><section><h3>Stream</h3><DataRow label="Kind" value={stream.kind} /><DataRow label="Frames" value={stream.frames.length.toString()} /></section><section><h3>Frames</h3>{stream.frames.length ? <div className="frame-list">{stream.frames.map((frame) => <article className="frame" key={frame.seq}><header><span className={`frame-direction ${frame.direction}`}>{frame.direction === 'up' ? '↑ sent' : '↓ received'}</span><code>#{frame.seq} · {frame.type} · {formatBytes(frame.size_bytes)}</code></header>{frame.type === 'sse' && frame.parsed != null ? <><small>Alanlar</small><CodeBlock text={JSON.stringify(frame.parsed, null, 2)} query={query} /></> : null}<small>Ham olay</small><CodeBlock text={bytesToText(decodeBase64(frame.raw))} query={query} /></article>)}</div> : <p className="empty-section">Frame bekleniyor.</p>}</section><section><h3>Reconstructed</h3><CodeBlock text={bytesToText(decodeBase64(stream.reconstructed))} query={query} /></section></div>
}

function ConnectionView({ detail }: { detail: SessionDetail }) {
  const { connection } = detail
  return <div className="detail-content"><section><h3>Connection</h3><DataRow label="Connection ID" value={detail.connection_id} /><DataRow label="Transport" value={connection.protocol.toUpperCase()} /><DataRow label="Client" value={connection.client_sockname ?? '—'} /><DataRow label="Server" value={connection.server_peername ?? '—'} /><DataRow label="Hostname" value={connection.server_hostname ?? '—'} /><DataRow label="HTTP version" value={detail.http_version ?? '—'} /><DataRow label="HTTP/2 stream" value={detail.http2_stream_id?.toString() ?? '—'} /></section><section><h3>TLS</h3><DataRow label="Established" value={connection.tls.established ? 'Yes' : 'No'} /><DataRow label="SNI" value={connection.tls.sni ?? '—'} /><DataRow label="Version" value={connection.tls.version ?? '—'} /><DataRow label="ALPN" value={connection.tls.alpn ?? '—'} /><DataRow label="Cipher" value={connection.tls.cipher ?? '—'} /></section>{connection.dns_query || connection.dns_answers.length ? <section><h3>DNS</h3><DataRow label="Query" value={connection.dns_query ?? '—'} /><DataRow label="Answers" value={connection.dns_answers.join(', ') || '—'} /><DataRow label="Duration" value={formatDuration(connection.dns_duration_ms)} /></section> : null}</div>
}

function RawView({ detail, query }: { detail: SessionDetail; query: string }) {
  const raw = useMemo(() => {
    const sections: string[] = []
    if (detail.request) {
      sections.push(`${detail.request.method} ${detail.request.path} ${detail.http_version ?? 'HTTP'}\n${headersToText(detail.request.headers)}\n\n${payloadText(detail.request.body, false)}`)
    }
    if (detail.response) {
      sections.push(`${detail.http_version ?? 'HTTP'} ${detail.response.status_code} ${detail.response.reason}\n${headersToText(detail.response.headers)}\n\n${payloadText(detail.response.body, false)}`)
    }
    return sections.join('\n\n──────── RESPONSE ────────\n\n')
  }, [detail])
  return <div className="detail-content raw-view"><section><h3>Raw HTTP</h3><CodeBlock text={raw || 'Ham veri yok.'} query={query} /></section></div>
}

function HexView({ detail }: { detail: SessionDetail }) {
  const requestBytes = detail.request ? decodeBase64(detail.request.body.raw) : new Uint8Array()
  const responseBytes = detail.response ? decodeBase64(detail.response.body.raw) : new Uint8Array()
  return <div className="detail-content"><section><h3>Request body · {formatBytes(requestBytes.length)}</h3><CodeBlock text={toHex(requestBytes)} /></section><section><h3>Response body · {formatBytes(responseBytes.length)}</h3><CodeBlock text={toHex(responseBytes)} /></section></div>
}

function BodySection({ payload, query }: { payload: Payload; query: string }) {
  return <section><h3>Body <span className="section-meta">{payload.detected_content_type ?? payload.declared_content_type ?? 'unknown'} · {formatBytes(payload.size_bytes)}{payload.content_encoding ? ` · ${payload.content_encoding}` : ''}</span></h3>{payload.is_truncated ? <p className="payload-warning">Gövde yakalama sınırında kesildi.</p> : null}<CodeBlock text={payloadText(payload, true) || 'Boş gövde'} query={query} /></section>
}

function HeaderSection({ title, headers }: { title: string; headers: Header[] }) {
  return <section><h3>{title} <span className="section-meta">{headers.length}</span></h3>{headers.length ? <div className="kv-list">{headers.map((header, index) => <div className="kv-row" key={`${header.name}-${index}`}><code>{header.name}</code><span>{header.value}</span></div>)}</div> : <p className="empty-section">Header yok.</p>}</section>
}

function PairSection({ title, values, empty }: { title: string; values: [string, string][]; empty: string }) {
  return <section><h3>{title} <span className="section-meta">{values.length}</span></h3>{values.length ? <div className="kv-list">{values.map(([key, value], index) => <div className="kv-row" key={`${key}-${index}`}><code>{key}</code><span>{value}</span></div>)}</div> : <p className="empty-section">{empty}</p>}</section>
}

function CodeBlock({ text, query = '' }: { text: string; query?: string }) {
  const clipped = text.length > BODY_TEXT_LIMIT ? `${text.slice(0, BODY_TEXT_LIMIT)}\n\n… Görüntü ${formatBytes(BODY_TEXT_LIMIT)} ile sınırlandı.` : text
  return <pre className="payload-code"><HighlightedText text={clipped} query={query} /></pre>
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query || query.startsWith('/')) return <>{text}</>
  const lower = text.toLocaleLowerCase('tr-TR')
  const needle = query.toLocaleLowerCase('tr-TR')
  const nodes: React.ReactNode[] = []
  let cursor = 0
  let match = lower.indexOf(needle)
  while (match >= 0 && nodes.length < 200) {
    nodes.push(text.slice(cursor, match), <mark key={match}>{text.slice(match, match + needle.length)}</mark>)
    cursor = match + needle.length
    match = lower.indexOf(needle, cursor)
  }
  nodes.push(text.slice(cursor))
  return <>{nodes}</>
}

function DetailMessage({ title, message, error = false }: { title: string; message: string; error?: boolean }) {
  return <div className={`detail-placeholder ${error ? 'detail-error' : ''}`}>{error ? <AlertTriangle size={20} /> : null}<h3>{title}</h3><p>{message}</p></div>
}

function SetupGuide({ certificate }: { certificate: CertificateStatus | null }) {
  const ready = certificate?.trusted ?? false
  const certificateLabel = certificate === null ? 'CA durumu kontrol ediliyor' : ready ? 'CA sertifikası hazır' : 'CA sertifikası kurulmamış'
  const certificateDetail = ready ? `${certificate?.trusted_machine ? 'Yerel Makine' : 'Kullanıcı'} güven deposunda doğrulandı.` : 'start.bat yeniden çalıştırıldığında güvenli kurulum onayı gösterilir.'
  return <div className="setup-guide"><div className="setup-icon"><LockKeyhole size={24} /></div><h3>Güvenli inceleme için hazırla</h3><p>Inspector sistem proxy ayarlarına dokunmaz. HTTPS gövdelerini görebilmek için yerel CA sertifikasının Windows güven deposunda olması gerekir.</p><div className={`setup-status ${ready ? 'ready' : ''}`}><ShieldCheck size={17} /><div><strong>{certificateLabel}</strong><span>{certificateDetail}</span></div></div><ol><li><span>1</span><div><strong>Yönetici olarak çalıştır</strong><small>WinDivert local capture için gereklidir.</small></div></li><li><span>2</span><div><strong>CA sertifikasını doğrula</strong><small>{ready ? 'Doğru parmak izi güven deposunda.' : 'start.bat bu adımı otomatik tamamlar.'}</small></div></li><li><span>3</span><div><strong>Capture’ı başlat</strong><small>Her uygulama varsayılan olarak kapsamda olur.</small></div></li></ol><div className="principle"><strong>Fail-open</strong><span>Inspector kapanırsa bağlantılar doğrudan internete devam eder.</span></div></div>
}

function DataRow({ label, value }: { label: string; value: string }) {
  return <div className="data-row"><span>{label}</span><code title={value}>{value}</code></div>
}

function decodeBase64(raw: string): Uint8Array {
  if (!raw) return new Uint8Array()
  let normalized = raw.replaceAll('-', '+').replaceAll('_', '/')
  normalized += '='.repeat((4 - normalized.length % 4) % 4)
  try {
    const decoded = window.atob(normalized)
    return Uint8Array.from(decoded, (char) => char.charCodeAt(0))
  } catch {
    return new Uint8Array()
  }
}

function bytesToText(bytes: Uint8Array) {
  return new TextDecoder('utf-8', { fatal: false }).decode(bytes)
}

function payloadText(payload: Payload, pretty: boolean) {
  if (pretty && payload.parsed !== null && typeof payload.parsed !== 'string') {
    return JSON.stringify(payload.parsed, null, 2)
  }
  if (pretty && typeof payload.parsed === 'string') return payload.parsed
  return bytesToText(decodeBase64(payload.raw))
}

function headersToText(headers: Header[]) {
  return headers.map((header) => `${header.name}: ${header.value}`).join('\n')
}

function toHex(bytes: Uint8Array) {
  if (!bytes.length) return 'Boş gövde'
  const limited = bytes.slice(0, HEX_LIMIT)
  const lines: string[] = []
  for (let offset = 0; offset < limited.length; offset += 16) {
    const row = limited.slice(offset, offset + 16)
    const hex = [...row].map((value) => value.toString(16).padStart(2, '0')).join(' ').padEnd(47)
    const ascii = [...row].map((value) => value >= 32 && value <= 126 ? String.fromCharCode(value) : '.').join('')
    lines.push(`${offset.toString(16).padStart(8, '0')}  ${hex}  |${ascii}|`)
  }
  if (bytes.length > HEX_LIMIT) lines.push(`\n… Hex görünümü ${formatBytes(HEX_LIMIT)} ile sınırlandı.`)
  return lines.join('\n')
}

function defaultPort(scheme: string, port: number) {
  return (scheme === 'https' && port === 443) || (scheme === 'http' && port === 80)
}

function formatBytes(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(duration: number | null) {
  if (duration == null) return '—'
  if (duration < 1000) return `${Math.round(duration)} ms`
  return `${(duration / 1000).toFixed(1)} s`
}
