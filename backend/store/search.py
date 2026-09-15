from __future__ import annotations

import regex as re
from collections.abc import Iterable
from typing import Any

from backend.inspect.content import decoded_payload_bytes
from backend.store.model import Header, Payload, Session


def _append(parts: list[str], key: str, value: Any) -> None:
    if value is None:
        return
    text = str(value)
    parts.extend((key, text, f"{key}:{text}"))


def _flatten(parts: list[str], value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _append(parts, "json_key", child_path)
            _flatten(parts, child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _flatten(parts, child, f"{path}.{index}" if path else str(index))
    elif path:
        _append(parts, path, value)
    elif value is not None:
        parts.append(str(value))


def _headers(parts: list[str], label: str, headers: Iterable[Header]) -> None:
    for header in headers:
        _append(parts, f"{label}_header", header.name)
        _append(parts, header.name, header.value)


def _payload(parts: list[str], label: str, payload: Payload) -> None:
    _append(parts, f"{label}_content_type", payload.detected_content_type)
    _append(parts, f"{label}_content_type", payload.declared_content_type)
    _flatten(parts, payload.parsed, label)
    decoded = decoded_payload_bytes(payload.raw, payload.content_encoding)
    if decoded and not payload.is_binary:
        parts.append(decoded.decode("utf-8", errors="replace"))


def build_search_document(session: Session) -> str:
    parts: list[str] = []
    for key, value in (
        ("application", session.application.name),
        ("executable", session.application.executable_path),
        ("pid", session.process.pid),
        ("process", session.process.name),
        ("protocol", session.type),
        ("http_version", session.http_version),
        ("host", session.connection.server_hostname),
        ("dns", session.connection.dns_query),
        ("inspection", session.connection.inspection_status.value),
        ("error", session.error),
    ):
        _append(parts, key, value)

    if session.request:
        request = session.request
        for key, value in (
            ("method", request.method),
            ("scheme", request.scheme),
            ("host", request.host),
            ("port", request.port),
            ("path", request.path),
            ("url", f"{request.scheme}://{request.host}:{request.port}{request.path}"),
        ):
            _append(parts, key, value)
        for key, value in request.query_params:
            _append(parts, key, value)
        for key, value in request.cookies:
            _append(parts, key, value)
        _headers(parts, "request", request.headers)
        _payload(parts, "request", request.body)

    if session.response:
        _append(parts, "status", session.response.status_code)
        _append(parts, "reason", session.response.reason)
        _headers(parts, "response", session.response.headers)
        for cookie in session.response.set_cookies:
            _append(parts, "set_cookie", cookie)
        _payload(parts, "response", session.response.body)

    if session.stream:
        _append(parts, "stream_kind", session.stream.kind)
        for frame in session.stream.frames:
            _append(parts, "frame_direction", frame.direction)
            if frame.raw:
                parts.append(frame.raw.decode("utf-8", errors="replace"))
            _flatten(parts, frame.parsed, f"frame.{frame.seq}")
        if session.stream.reconstructed:
            parts.append(session.stream.reconstructed.decode("utf-8", errors="replace"))
    return "\n".join(parts).casefold()


def matches_search(document: str, query: str) -> bool:
    normalized = query.strip()
    if not normalized:
        return True
    if len(normalized) > 2 and normalized.startswith("/") and normalized.endswith("/"):
        try:
            return re.search(normalized[1:-1], document, re.IGNORECASE, timeout=0.05) is not None
        except TimeoutError as exc:
            raise ValueError("Arama deseni çok uzun sürüyor; daha basit bir desen kullanın") from exc
        except re.error:
            return False
    return normalized.casefold() in document
