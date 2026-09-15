import gzip
import zlib

import brotli
import zstandard

from backend.inspect import content
from backend.inspect.content import decoded_payload_bytes, inspect_payload
from backend.store.model import Connection, Request, Session
from backend.store.search import build_search_document


def test_json_payload_is_detected_parsed_and_keeps_raw_bytes() -> None:
    raw = b'{"nested":{"message":"selam"}}'
    payload = inspect_payload(
        raw,
        original_size=len(raw),
        declared_content_type="application/octet-stream",
        content_encoding=None,
        is_truncated=False,
    )

    assert payload.raw == raw
    assert payload.detected_content_type == "application/json"
    assert payload.parsed == {"nested": {"message": "selam"}}
    assert payload.is_binary is False


def test_gzip_payload_is_decoded_for_inspection_without_changing_raw() -> None:
    decoded = b'{"message":"compressed"}'
    raw = gzip.compress(decoded)
    payload = inspect_payload(
        raw,
        original_size=len(raw),
        declared_content_type="application/json",
        content_encoding="gzip",
        is_truncated=False,
    )

    assert payload.raw == raw
    assert payload.parsed == {"message": "compressed"}


def test_zstd_streaming_frame_without_content_size_is_searchable() -> None:
    decoded = b'{"nested":{"message":"selam"}}'
    raw = zstandard.ZstdCompressor(write_content_size=False).compress(decoded)
    payload = inspect_payload(
        raw,
        original_size=len(raw),
        declared_content_type="application/json",
        content_encoding="zstd",
        is_truncated=False,
    )

    assert payload.raw == raw
    assert payload.parsed == {"nested": {"message": "selam"}}
    session = Session(
        connection_id="zstd", type="http", connection=Connection(),
        request=Request(method="POST", scheme="https", host="example.test",
                        port=443, path="/messages", body=payload),
    )
    assert "selam" in build_search_document(session)


def test_partial_gzip_does_not_drop_session_during_search() -> None:
    raw = gzip.compress(b'{"message":"selam"}')[:-4]
    assert decoded_payload_bytes(raw, "gzip") == raw
    payload = inspect_payload(
        raw,
        original_size=len(raw),
        declared_content_type="application/json",
        content_encoding="gzip",
        is_truncated=True,
    )
    assert payload.raw == raw


def test_oversized_decoded_payload_falls_back_to_original_bytes(monkeypatch) -> None:
    monkeypatch.setattr(content, "MAX_DECODED_BYTES", 64)
    decoded = b"x" * 65
    for encoding, raw in (
        ("gzip", gzip.compress(decoded)),
        ("deflate", zlib.compress(decoded)),
        ("br", brotli.compress(decoded)),
        ("zstd", zstandard.ZstdCompressor().compress(decoded)),
    ):
        assert decoded_payload_bytes(raw, encoding) == raw
