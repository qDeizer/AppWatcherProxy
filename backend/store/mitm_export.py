from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from mitmproxy import connection, http, websocket
from mitmproxy.io import FlowWriter
from wsproto.frame_protocol import Opcode

from backend.store.model import Header, Session
from backend.store.recorder import read_recording


def _headers(values: list[Header]) -> list[tuple[bytes, bytes]]:
    return [(item.name.encode("utf-8", errors="surrogateescape"),
             item.value.encode("utf-8", errors="surrogateescape")) for item in values]


def _url(session: Session) -> str:
    request = session.request
    host = request.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    path = request.path if request.path.startswith("/") else f"/{request.path}"
    return f"{request.scheme}://{host}:{request.port}{path}"


def can_export(session: Session) -> bool:
    if session.type not in {"http", "websocket"} or session.request is None:
        return False
    if session.is_truncated or session.is_streaming or session.response is None:
        return False
    if session.request.body.is_truncated or session.response.body.is_truncated:
        return False
    return session.type != "websocket" or session.stream is not None


def to_flow(session: Session) -> http.HTTPFlow:
    if not can_export(session):
        raise ValueError("Oturum replay için eksik veya desteklenmiyor")
    request = session.request
    response = session.response
    client = connection.Client(peername=("0.0.0.0", 0), sockname=("0.0.0.0", 0))
    server = connection.Server(address=(request.host, request.port))
    flow = http.HTTPFlow(client, server)
    flow.id = session.id
    flow.request = http.Request.make(request.method, _url(session), request.body.raw, _headers(request.headers))
    flow.request.http_version = (session.http_version or "HTTP/1.1").encode("ascii", errors="replace")
    flow.request.timestamp_start = session.opened_at.timestamp()
    flow.request.timestamp_end = session.opened_at.timestamp()
    flow.response = http.Response.make(response.status_code, response.body.raw, _headers(response.headers))
    flow.response.http_version = flow.request.http_version
    flow.response.reason = response.reason.encode("utf-8", errors="replace")
    flow.response.timestamp_end = (session.closed_at or session.opened_at).timestamp()
    if session.type == "websocket":
        messages = []
        opcodes = {
            "text": Opcode.TEXT, "1": Opcode.TEXT,
            "binary": Opcode.BINARY, "2": Opcode.BINARY,
            "ping": Opcode.PING, "9": Opcode.PING,
            "pong": Opcode.PONG, "10": Opcode.PONG,
            "close": Opcode.CLOSE, "8": Opcode.CLOSE,
        }
        for frame in session.stream.frames:
            opcode = opcodes.get(frame.type.casefold(), Opcode.TEXT)
            messages.append(websocket.WebSocketMessage(
                type=opcode, from_client=frame.direction == "up", content=frame.raw,
                timestamp=frame.timestamp.timestamp(),
            ))
        flow.websocket = websocket.WebSocketData(messages=messages)
    return flow


@dataclass(frozen=True)
class ExportPlan:
    supported: int
    skipped: int
    positions: frozenset[int]


def inspect_recording(path: Path, password: str | None = None) -> ExportPlan:
    latest: dict[str, tuple[int, bool]] = {}
    for position, session in enumerate(read_recording(path, password)):
        eligible = can_export(session)
        if eligible:
            to_flow(session)
        latest[session.id] = (position, eligible)
    positions = frozenset(position for position, eligible in latest.values() if eligible)
    return ExportPlan(len(positions), len(latest) - len(positions), positions)


def mitm_chunks(path: Path, password: str | None = None, positions: frozenset[int] | None = None) -> Iterator[bytes]:
    selected = positions if positions is not None else inspect_recording(path, password).positions
    for position, session in enumerate(read_recording(path, password)):
        if position not in selected:
            continue
        output = BytesIO()
        FlowWriter(output).add(to_flow(session))
        yield output.getvalue()
