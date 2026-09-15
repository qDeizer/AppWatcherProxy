from __future__ import annotations


class ChunkCapture:
    """Keep bounded copies of streamed bytes without delaying the client."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.total_bytes = 0
        self.raw = bytearray()
        self.truncated = False

    def feed(self, chunk: bytes) -> bytes:
        self.total_bytes += len(chunk)
        remaining = max(0, self.max_bytes - len(self.raw))
        captured = chunk[:remaining]
        self.raw.extend(captured)
        self.truncated |= len(captured) < len(chunk)
        return captured
