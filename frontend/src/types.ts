export type CaptureState = 'stopped' | 'starting' | 'running' | 'stopping' | 'error'

export interface Stats {
  session_count: number
  memory_bytes: number
  open_connections: number
  capture_state: CaptureState
  capture_error: string | null
  recording: boolean
  recording_error?: string | null
  processing_error?: string | null
}

export interface CertificateStatus {
  exists: boolean
  subject: string | null
  thumbprint: string | null
  not_after: string | null
  trusted_user: boolean
  trusted_machine: boolean
  trusted: boolean
}

export interface ProcessSummary {
  pid: number
  name: string
}

export interface ApplicationSummary {
  name: string
  executable_path: string | null
  session_count: number
  process_count: number
  processes: ProcessSummary[]
}

export type Inspection = 'Full' | 'Metadata Only' | 'Encrypted' | 'Unsupported'

export interface SessionSummary {
  id: string
  time: string
  application: string
  pid: number | null
  direction: 'up' | 'down'
  protocol: string
  host: string | null
  method_event: string
  path: string
  status: number | null
  content_type: string | null
  sent: number
  received: number
  duration_ms: number | null
  inspection: Inspection
  inspection_reason: string | null
  is_streaming: boolean
  has_error: boolean
  is_binary: boolean
}

export interface SessionPage {
  items: SessionSummary[]
  total: number
}

export interface Header {
  name: string
  value: string
}

export interface Payload {
  raw: string
  parsed: unknown
  declared_content_type: string | null
  detected_content_type: string | null
  content_encoding: string | null
  size_bytes: number
  is_truncated: boolean
  is_binary: boolean
}

export interface RequestDetail {
  method: string
  scheme: string
  host: string
  port: number
  path: string
  query_params: [string, string][]
  headers: Header[]
  cookies: [string, string][]
  body: Payload
}

export interface ResponseDetail {
  status_code: number
  reason: string
  headers: Header[]
  set_cookies: string[]
  body: Payload
  ttfb_ms: number | null
  total_ms: number | null
}

export interface StreamFrame {
  seq: number
  timestamp: string
  direction: 'up' | 'down'
  size_bytes: number
  type: string
  raw: string
  parsed: unknown
}

export interface SessionStream {
  kind: 'sse' | 'chunked' | 'h2_data' | 'websocket' | 'grpc' | 'raw_tcp'
  frames: StreamFrame[]
  reconstructed: string
}

export interface SessionDetail {
  id: string
  connection_id: string
  type: string
  opened_at: string
  closed_at: string | null
  duration_ms: number | null
  http_version: string | null
  http2_stream_id: number | null
  error: string | null
  application: { name: string; executable_path: string | null; icon: string | null }
  process: { pid: number | null; name: string; executable_path: string | null; start_time: string | null }
  connection: {
    id: string
    opened_at: string
    closed_at: string | null
    protocol: string
    client_sockname: string | null
    server_peername: string | null
    server_hostname: string | null
    dns_query: string | null
    dns_answers: string[]
    dns_duration_ms: number | null
    inspection_status: Inspection
    inspection_reason: string | null
    tls: {
      version: string | null
      cipher: string | null
      alpn: string | null
      sni: string | null
      established: boolean
      handshake_error: string | null
    }
  }
  request: RequestDetail | null
  response: ResponseDetail | null
  stream: SessionStream | null
  is_streaming: boolean
  is_truncated: boolean
  has_error: boolean
  is_binary: boolean
}
