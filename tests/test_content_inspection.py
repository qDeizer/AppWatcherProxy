import gzip

from backend.inspect.content import inspect_payload


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
