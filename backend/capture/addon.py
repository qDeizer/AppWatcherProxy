from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.capture.processes import find_connection_pid, resolve_process
from backend.inspect.content import decoded_payload_bytes, inspect_payload
from backend.store.model import (
    Connection,
    Frame,
    Header,
    InspectionStatus,
    Request,
    Response,
    Session,
    Stream,
)


def _address(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, tuple):
        return ":".join(str(part) for part in value)
    return str(value)


def _headers(headers: Any) -> list[Header]:
    return [Header(name=str(k), value=str(v)) for k, v in headers.items(multi=True)]


def _timestamp(value: float | None, fallback: datetime | None = None) -> datetime:
    if value is not None:
        return datetime.fromtimestamp(value, UTC)
    return fallback or datetime.now(UTC)


class InspectorAddon:
    def __init__(self, on_session: Any, max_body_bytes: int) -> None:
        self.on_session = on_session
        self.max_body_bytes = max_body_bytes
        self._pending: dict[str, Session] = {}

    def _identity(self, flow: Any) -> tuple[Any, Any]:
        client = flow.client_conn
        server = flow.server_conn
        pid = find_connection_pid(
            getattr(client, "peername", None), getattr(server, "peername", None)
        )
        return resolve_process(pid)

    def _connection(
        self,
        flow: Any,
        status: InspectionStatus = InspectionStatus.FULL,
        reason: str | None = None,
    ) -> Connection:
        client = flow.client_conn
        server = flow.server_conn
        address = getattr(server, "address", None)
        return Connection(
            client_sockname=_address(getattr(client, "sockname", None)),
            server_peername=_address(getattr(server, "peername", None)),
            server_hostname=address[0] if address else None,
            inspection_status=status,
            inspection_reason=reason,
            tls={
                "version": getattr(server, "tls_version", None),
                "cipher": getattr(server, "cipher", None),
                "alpn": getattr(server, "alpn", None),
                "sni": getattr(server, "sni", None),
                "established": bool(getattr(server, "tls_established", False)),
            },
        )

    def _request(self, flow: Any) -> Request:
        original = bytes(flow.request.raw_content or b"")
        truncated = len(original) > self.max_body_bytes
        raw = original[: self.max_body_bytes]
        return Request(
            method=flow.request.method,
            scheme=flow.request.scheme,
            host=flow.request.host,
            port=flow.request.port,
            path=flow.request.path,
            query_params=list(flow.request.query.items(multi=True)),
            headers=_headers(flow.request.headers),
            cookies=list(flow.request.cookies.items(multi=True)),
            body=inspect_payload(
                raw,
                original_size=len(original),
                declared_content_type=flow.request.headers.get("content-type"),
                content_encoding=flow.request.headers.get("content-encoding"),
                is_truncated=truncated,
            ),
        )

    def _response(self, flow: Any) -> Response:
        original = bytes(flow.response.raw_content or b"")
        truncated = len(original) > self.max_body_bytes
        raw = original[: self.max_body_bytes]
        completed = _timestamp(
            flow.response.timestamp_end,
            _timestamp(flow.request.timestamp_start),
        )
        started = _timestamp(flow.request.timestamp_start)
        return Response(
            status_code=flow.response.status_code,
            reason=flow.response.reason or "",
            headers=_headers(flow.response.headers),
            set_cookies=flow.response.headers.get_all("set-cookie"),
            body=inspect_payload(
                raw,
                original_size=len(original),
                declared_content_type=flow.response.headers.get("content-type"),
                content_encoding=flow.response.headers.get("content-encoding"),
                is_truncated=truncated,
            ),
            total_ms=(completed - started).total_seconds() * 1000,
        )

    def _new_http_session(self, flow: Any) -> Session:
        application, process = self._identity(flow)
        request = self._request(flow)
        return Session(
            connection_id=str(flow.id),
            type="http",
            opened_at=_timestamp(flow.request.timestamp_start),
            http_version=flow.request.http_version,
            application=application,
            process=process,
            connection=self._connection(flow),
            request=request,
            is_truncated=request.body.is_truncated,
            is_binary=request.body.is_binary,
        )

    async def request(self, flow: Any) -> None:
        """Publish immediately so long-running requests are visible before completion."""
        if flow.id in self._pending:
            return
        session = self._new_http_session(flow)
        self._pending[flow.id] = session
        await self.on_session(session)

    async def response(self, flow: Any) -> None:
        session = self._pending.get(flow.id) or self._new_http_session(flow)
        response = self._response(flow)
        completed = _timestamp(flow.response.timestamp_end, session.opened_at)
        session.response = response
        session.closed_at = completed
        session.duration_ms = (completed - session.opened_at).total_seconds() * 1000
        session.is_truncated = session.is_truncated or response.body.is_truncated
        session.is_binary = session.is_binary or response.body.is_binary

        content_type = (response.body.detected_content_type or "").casefold()
        if content_type == "text/event-stream":
            reconstructed = decoded_payload_bytes(
                response.body.raw, response.body.content_encoding
            )
            chunks = [
                chunk
                for chunk in reconstructed.replace(b"\r\n", b"\n").split(b"\n\n")
                if chunk
            ]
            session.stream = Stream(
                kind="sse",
                reconstructed=reconstructed,
                frames=[
                    Frame(
                        seq=index,
                        timestamp=completed,
                        direction="down",
                        size_bytes=len(chunk),
                        type="sse",
                        raw=chunk,
                    )
                    for index, chunk in enumerate(chunks)
                ],
            )
            session.is_streaming = True

        await self.on_session(session)
        if getattr(flow, "websocket", None) is None:
            self._pending.pop(flow.id, None)

    async def websocket_start(self, flow: Any) -> None:
        session = self._pending.get(flow.id) or self._new_http_session(flow)
        if flow.response is not None:
            session.response = self._response(flow)
        session.type = "websocket"
        session.stream = Stream(kind="websocket")
        session.is_streaming = True
        session.closed_at = None
        self._pending[flow.id] = session
        await self.on_session(session)

    async def websocket_message(self, flow: Any) -> None:
        session = self._pending.get(flow.id)
        if session is None:
            await self.websocket_start(flow)
            session = self._pending[flow.id]
        if not flow.websocket or not flow.websocket.messages:
            return
        message = flow.websocket.messages[-1]
        raw = bytes(message.content or b"")
        stream = session.stream or Stream(kind="websocket")
        captured = len(stream.reconstructed)
        remaining = max(0, self.max_body_bytes - captured)
        frame_raw = raw[:remaining]
        message_type = str(getattr(message, "type", "message")).split(".")[-1].casefold()
        stream.frames.append(
            Frame(
                seq=len(stream.frames),
                timestamp=_timestamp(getattr(message, "timestamp", None)),
                direction="up" if message.from_client else "down",
                size_bytes=len(raw),
                type=message_type,
                raw=frame_raw,
                parsed=inspect_payload(
                    frame_raw,
                    original_size=len(raw),
                    declared_content_type=(
                        "text/plain" if message_type == "text" else "application/octet-stream"
                    ),
                    content_encoding=None,
                    is_truncated=len(frame_raw) < len(raw),
                ).parsed,
            )
        )
        stream.reconstructed += frame_raw
        session.stream = stream
        session.is_truncated = session.is_truncated or len(frame_raw) < len(raw)
        session.is_binary = session.is_binary or message_type == "binary"
        await self.on_session(session)

    async def websocket_end(self, flow: Any) -> None:
        session = self._pending.pop(flow.id, None)
        if session is None:
            return
        session.closed_at = datetime.now(UTC)
        session.duration_ms = (session.closed_at - session.opened_at).total_seconds() * 1000
        await self.on_session(session)

    async def error(self, flow: Any) -> None:
        if not getattr(flow, "error", None):
            return
        message = str(flow.error)
        encrypted = "tls" in message.casefold() or "certificate" in message.casefold()
        status = InspectionStatus.ENCRYPTED if encrypted else InspectionStatus.METADATA_ONLY
        reason = (
            "TLS el sıkışması başarısız; uygulama sertifika sabitlemesi yapıyor olabilir."
            if encrypted
            else message
        )
        session = self._pending.pop(flow.id, None)
        if session is None:
            application, process = self._identity(flow)
            connection = self._connection(flow, status, reason)
            session = Session(
                connection_id=connection.id,
                type="handshake_failed" if encrypted else "tcp",
                application=application,
                process=process,
                connection=connection,
            )
        else:
            session.type = "handshake_failed" if encrypted else "tcp"
            session.connection.inspection_status = status
            session.connection.inspection_reason = reason
        session.error = message
        session.has_error = True
        session.closed_at = datetime.now(UTC)
        session.duration_ms = (session.closed_at - session.opened_at).total_seconds() * 1000
        await self.on_session(session)
