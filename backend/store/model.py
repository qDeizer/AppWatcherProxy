from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class InspectionStatus(StrEnum):
    FULL = "Full"
    METADATA_ONLY = "Metadata Only"
    ENCRYPTED = "Encrypted"
    UNSUPPORTED = "Unsupported"


class Header(BaseModel):
    name: str
    value: str


class Payload(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    raw: bytes = b""
    parsed: Any | None = None
    declared_content_type: str | None = None
    detected_content_type: str | None = None
    content_encoding: str | None = None
    size_bytes: int = 0
    is_truncated: bool = False
    is_binary: bool = False


class Frame(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    seq: int
    timestamp: datetime = Field(default_factory=utc_now)
    direction: Literal["up", "down"]
    size_bytes: int
    type: str
    raw: bytes
    parsed: Any | None = None


class Stream(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    kind: Literal["sse", "chunked", "h2_data", "websocket", "grpc", "raw_tcp"]
    frames: list[Frame] = Field(default_factory=list)
    reconstructed: bytes = b""


class Request(BaseModel):
    method: str
    scheme: str
    host: str
    port: int
    path: str
    query_params: list[tuple[str, str]] = Field(default_factory=list)
    headers: list[Header] = Field(default_factory=list)
    cookies: list[tuple[str, str]] = Field(default_factory=list)
    body: Payload = Field(default_factory=Payload)


class Response(BaseModel):
    status_code: int
    reason: str = ""
    headers: list[Header] = Field(default_factory=list)
    set_cookies: list[str] = Field(default_factory=list)
    body: Payload = Field(default_factory=Payload)
    ttfb_ms: float | None = None
    total_ms: float | None = None


class ProcessInfo(BaseModel):
    pid: int | None = None
    name: str = "Unknown"
    executable_path: str | None = None
    start_time: datetime | None = None


class ApplicationInfo(BaseModel):
    name: str = "Unknown"
    executable_path: str | None = None
    icon: str | None = None


class TlsInfo(BaseModel):
    version: str | None = None
    cipher: str | None = None
    alpn: str | None = None
    sni: str | None = None
    established: bool = False
    handshake_error: str | None = None


class Connection(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    protocol: Literal["tcp", "udp", "quic"] = "tcp"
    client_sockname: str | None = None
    server_peername: str | None = None
    server_hostname: str | None = None
    dns_query: str | None = None
    dns_answers: list[str] = Field(default_factory=list)
    dns_duration_ms: float | None = None
    tls: TlsInfo = Field(default_factory=TlsInfo)
    inspection_status: InspectionStatus = InspectionStatus.METADATA_ONLY
    inspection_reason: str | None = None


class Session(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    id: str = Field(default_factory=lambda: str(uuid4()))
    connection_id: str
    type: Literal["http", "websocket", "tcp", "dns", "handshake_failed"]
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    duration_ms: float | None = None
    http_version: str | None = None
    http2_stream_id: int | None = None
    error: str | None = None
    application: ApplicationInfo = Field(default_factory=ApplicationInfo)
    process: ProcessInfo = Field(default_factory=ProcessInfo)
    connection: Connection
    request: Request | None = None
    response: Response | None = None
    stream: Stream | None = None
    is_streaming: bool = False
    is_truncated: bool = False
    has_error: bool = False
    is_binary: bool = False

    def summary(self) -> dict[str, Any]:
        request = self.request
        response = self.response
        sent = request.body.size_bytes if request else 0
        received = response.body.size_bytes if response else 0
        return {
            "id": self.id,
            "time": self.opened_at.isoformat(),
            "application": self.application.name,
            "pid": self.process.pid,
            "direction": "up",
            "protocol": self.type.upper(),
            "host": request.host if request else self.connection.server_hostname,
            "method_event": request.method if request else self.type,
            "path": request.path if request else "",
            "status": response.status_code if response else None,
            "content_type": (
                (response.body.detected_content_type or response.body.declared_content_type)
                if response
                else (
                    request.body.detected_content_type or request.body.declared_content_type
                    if request
                    else None
                )
            ),
            "sent": sent,
            "received": received,
            "duration_ms": self.duration_ms,
            "inspection": self.connection.inspection_status.value,
            "inspection_reason": self.connection.inspection_reason,
            "is_streaming": self.is_streaming,
            "has_error": self.has_error,
            "is_binary": self.is_binary,
        }
