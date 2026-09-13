from __future__ import annotations

import gzip
import json
import zlib
from urllib.parse import parse_qsl

import brotli
import zstandard

from backend.store.model import Payload


TEXT_CONTENT_TYPES = (
    "application/json",
    "application/graphql",
    "application/javascript",
    "application/x-www-form-urlencoded",
    "application/xml",
    "application/yaml",
    "image/svg+xml",
    "text/",
)


def decoded_payload_bytes(raw: bytes, content_encoding: str | None) -> bytes:
    """Return a best-effort decoded copy while preserving the original bytes elsewhere."""
    if not raw or not content_encoding:
        return raw
    value = raw
    encodings = [item.strip().casefold() for item in content_encoding.split(",") if item.strip()]
    try:
        for encoding in reversed(encodings):
            if encoding == "gzip":
                value = gzip.decompress(value)
            elif encoding == "deflate":
                try:
                    value = zlib.decompress(value)
                except zlib.error:
                    value = zlib.decompress(value, -zlib.MAX_WBITS)
            elif encoding == "br":
                value = brotli.decompress(value)
            elif encoding in {"zstd", "zstandard"}:
                value = zstandard.ZstdDecompressor().decompress(value)
        return value
    except (OSError, ValueError, zlib.error, brotli.error, zstandard.ZstdError):
        return raw


def _declared_base(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().casefold()


def _decode_text(value: bytes) -> str:
    if not value:
        return ""
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def _looks_binary(value: bytes) -> bool:
    if not value:
        return False
    sample = value[:4096]
    if b"\x00" in sample:
        return True
    control = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return control / len(sample) > 0.08


def inspect_payload(
    raw: bytes,
    *,
    original_size: int,
    declared_content_type: str | None,
    content_encoding: str | None,
    is_truncated: bool,
) -> Payload:
    decoded = decoded_payload_bytes(raw, content_encoding)
    declared = _declared_base(declared_content_type)
    text = _decode_text(decoded)
    stripped = text.lstrip()
    parsed: object | None = None
    detected: str | None = declared or None

    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            detected = "application/json"
        except json.JSONDecodeError:
            pass
    elif declared == "application/x-www-form-urlencoded":
        parsed = dict(parse_qsl(text, keep_blank_values=True))
        detected = declared
    elif stripped.startswith("<") and stripped.endswith(">"):
        detected = "application/xml" if "xml" in declared else "text/xml"

    declared_is_text = any(
        declared == item or (item.endswith("/") and declared.startswith(item))
        for item in TEXT_CONTENT_TYPES
    )
    is_binary = bool(decoded) and not declared_is_text and parsed is None and _looks_binary(decoded)
    if detected is None and decoded:
        detected = "application/octet-stream" if is_binary else "text/plain"
    if parsed is None and decoded and not is_binary:
        parsed = text

    return Payload(
        raw=raw,
        parsed=parsed,
        declared_content_type=declared_content_type,
        detected_content_type=detected,
        content_encoding=content_encoding,
        size_bytes=original_size,
        is_truncated=is_truncated,
        is_binary=is_binary,
    )
