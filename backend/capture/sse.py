from __future__ import annotations

import json
import zlib


def parse_event(lines: list[bytes]) -> dict | None:
    fields: dict[str, object] = {}
    data: list[str] = []
    has_data = False
    for line in lines:
        if not line or line.startswith(b":"):
            continue
        name, _, value = line.partition(b":")
        if value.startswith(b" "):
            value = value[1:]
        key = name.decode("utf-8", errors="replace")
        text = value.decode("utf-8", errors="replace")
        if key == "data":
            has_data = True
            data.append(text)
        elif key in {"event", "id", "retry"}:
            fields[key] = text
    if not has_data:
        return None
    payload = "\n".join(data)
    try:
        fields["data"] = json.loads(payload)
    except (ValueError, TypeError, RecursionError):
        fields["data"] = payload
    return fields


class SSECapture:
    def __init__(self, max_bytes: int, content_encoding: str | None = None) -> None:
        self.max_bytes = max_bytes
        self.total_bytes = 0
        self.raw = bytearray()
        self.reconstructed = bytearray()
        self.truncated = False
        encoding = (content_encoding or "").strip().casefold()
        self.supports_live = encoding in {"", "identity", "gzip", "deflate"}
        self.decoding_failed = not self.supports_live
        self._decoder = (
            zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip"
            else zlib.decompressobj() if encoding == "deflate" else None
        )
        self._pending = bytearray()
        self._line_start = 0
        self._position = 0
        self._lines: list[bytes] = []
        self._event_count = 0

    def feed(self, chunk: bytes) -> list[tuple[bytes, dict]]:
        if not chunk:
            return []
        self.total_bytes += len(chunk)
        remaining = max(0, self.max_bytes - len(self.raw))
        captured = chunk[:remaining]
        self.truncated |= len(captured) < len(chunk)
        self.raw.extend(captured)
        if len(self.reconstructed) >= self.max_bytes:
            return []
        if self._decoder and not self.decoding_failed:
            try:
                decoded = self._decoder.decompress(captured, max(1, self.max_bytes - len(self.reconstructed) + 1))
            except zlib.error:
                self.decoding_failed = True
                return []
        elif self.decoding_failed:
            return []
        else:
            decoded = captured
        decoded_remaining = max(0, self.max_bytes - len(self.reconstructed))
        self.truncated |= len(decoded) > decoded_remaining
        decoded = decoded[:decoded_remaining]
        self.reconstructed.extend(decoded)
        if self._event_count >= 10_000:
            self.truncated = True
            return []
        self._pending.extend(decoded)
        events: list[tuple[bytes, dict]] = []
        while self._position < len(self._pending):
            current = self._pending[self._position]
            if current not in (10, 13):
                self._position += 1
                continue
            if current == 13 and self._position + 1 == len(self._pending):
                break
            ending = self._position + (2 if current == 13 and self._pending[self._position + 1] == 10 else 1)
            line = bytes(self._pending[self._line_start:self._position])
            if line:
                self._lines.append(line)
            else:
                parsed = parse_event(self._lines)
                if parsed is not None:
                    if self._event_count >= 10_000:
                        self.truncated = True
                        self._pending.clear()
                        self._lines.clear()
                        self._position = 0
                        self._line_start = 0
                        return events
                    self._event_count += 1
                    events.append((bytes(self._pending[:ending]), parsed))
                del self._pending[:ending]
                self._position = 0
                self._line_start = 0
                self._lines.clear()
                continue
            self._position = ending
            self._line_start = ending
        return events
