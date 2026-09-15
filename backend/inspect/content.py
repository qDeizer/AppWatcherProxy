from __future__ import annotations

import gzip
import json
import zlib
from io import BytesIO
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

MAX_DECODED_BYTES = 64 * 1024 * 1024


def _decompress_gzip(value: bytes) -> bytes:
    with gzip.GzipFile(fileobj=BytesIO(value)) as source:
        decoded = source.read(MAX_DECODED_BYTES + 1)
        if len(decoded) <= MAX_DECODED_BYTES and source.read(1):
            raise ValueError("Decoded payload exceeds inspection limit")
    if len(decoded) > MAX_DECODED_BYTES:
        raise ValueError("Decoded payload exceeds inspection limit")
    return decoded


def _decompress_deflate(value: bytes) -> bytes:
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            decoder = zlib.decompressobj(wbits)
            decoded = decoder.decompress(value, MAX_DECODED_BYTES + 1)
            if len(decoded) > MAX_DECODED_BYTES or decoder.unconsumed_tail or not decoder.eof:
                raise ValueError("Decoded payload exceeds inspection limit or is incomplete")
            decoded += decoder.flush(MAX_DECODED_BYTES + 1 - len(decoded))
            if len(decoded) > MAX_DECODED_BYTES:
                raise ValueError("Decoded payload exceeds inspection limit")
            return decoded
        except zlib.error:
            continue
    raise zlib.error("Invalid deflate payload")


def _decompress_brotli(value: bytes) -> bytes:
    decoder = brotli.Decompressor()
    parts: list[bytes] = []
    total = 0
    for offset in range(0, len(value), 4096):
        part = decoder.process(value[offset:offset + 4096])
        total += len(part)
        if total > MAX_DECODED_BYTES:
            raise ValueError("Decoded payload exceeds inspection limit")
        parts.append(part)
    if not decoder.is_finished():
        raise ValueError("Incomplete brotli payload")
    return b"".join(parts)


def decoded_payload_bytes(raw: bytes, content_encoding: str | None) -> bytes:
    """Return a best-effort decoded copy while preserving the original bytes elsewhere."""
    if not raw or not content_encoding:
        return raw
    value = raw
    encodings = [item.strip().casefold() for item in content_encoding.split(",") if item.strip()]
    try:
        for encoding in reversed(encodings):
            if encoding == "gzip":
                value = _decompress_gzip(value)
            elif encoding == "deflate":
                value = _decompress_deflate(value)
            elif encoding == "br":
                value = _decompress_brotli(value)
            elif encoding in {"zstd", "zstandard"}:
                # Streaming zstd frames commonly omit the decompressed size.
                # Without an explicit bound, python-zstandard refuses those
                # frames even though the captured bytes are complete.
                declared_size = zstandard.frame_content_size(value)
                if declared_size >= 0 and declared_size > MAX_DECODED_BYTES:
                    raise ValueError("Decoded payload exceeds inspection limit")
                value = zstandard.ZstdDecompressor().decompress(
                    value, max_output_size=MAX_DECODED_BYTES
                )
                if len(value) > MAX_DECODED_BYTES:
                    raise ValueError("Decoded payload exceeds inspection limit")
        return value
    except (EOFError, OSError, ValueError, zlib.error, brotli.error, zstandard.ZstdError):
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
        except (ValueError, RecursionError):
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
