import asyncio
import gzip
from datetime import UTC, datetime

import brotli
import zstandard
from mitmproxy.test import tflow

from backend.capture.addon import InspectorAddon
from backend.capture.sse import SSECapture
from backend.store.model import ApplicationInfo, ProcessInfo
from backend.store.recorder import Recorder, read_recording


def _identity(_flow):
    return ApplicationInfo(name="test.exe"), ProcessInfo(pid=123, name="test.exe")


async def test_shutdown_waits_for_pending_stream_publish():
    started = asyncio.Event()
    release = asyncio.Event()
    published = []
    async def on_session(session):
        started.set()
        await release.wait()
        published.append(session)
    addon = InspectorAddon(on_session, 1024)
    addon._publish_sse("flow", "last snapshot")
    await started.wait()
    closing = asyncio.create_task(addon.done())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    assert published == ["last snapshot"]
    assert not addon._sse_tasks


async def test_http_request_is_published_before_response_and_updated_in_place() -> None:
    published = []

    async def on_session(session):
        published.append(session.model_copy(deep=True))

    flow = tflow.tflow(resp=True)
    flow.request.content = b'{"message":"selam"}'
    flow.request.headers["content-type"] = "application/json"
    flow.response.content = b'{"ok":true}'
    flow.response.headers["content-type"] = "application/json"
    addon = InspectorAddon(on_session, max_body_bytes=1024)
    addon._identity = _identity

    await addon.request(flow)
    await addon.response(flow)

    assert len(published) == 2
    assert published[0].id == published[1].id
    assert published[0].response is None
    assert published[1].response.status_code == 200
    assert published[1].request.body.parsed == {"message": "selam"}
    assert published[1].response.body.parsed == {"ok": True}


async def test_websocket_messages_are_added_as_searchable_frames() -> None:
    published = []

    async def on_session(session):
        published.append(session.model_copy(deep=True))

    flow = tflow.twebsocketflow()
    addon = InspectorAddon(on_session, max_body_bytes=1024)
    addon._identity = _identity

    await addon.request(flow)
    await addon.websocket_start(flow)
    await addon.websocket_message(flow)

    session = published[-1]
    assert session.type == "websocket"
    assert session.is_streaming is True
    assert session.stream.kind == "websocket"
    assert session.stream.frames[-1].raw == flow.websocket.messages[-1].content
    assert session.stream.frames[-1].type == "text"


async def test_websocket_retention_and_eviction_are_bounded():
    async def on_session(session):
        pass
    flow = tflow.twebsocketflow()
    addon = InspectorAddon(on_session, max_body_bytes=1)
    addon._identity = _identity
    await addon.websocket_start(flow)
    await addon.websocket_message(flow)
    await addon.websocket_message(flow)
    session = addon._pending[flow.id]
    assert len(session.stream.reconstructed) == 1
    assert len(session.stream.frames) == 1
    assert len(flow.websocket.messages) == 1
    assert session.is_truncated
    addon.discard([session.id])
    assert addon._pending
    await addon.websocket_end(flow)
    assert not addon._pending


async def test_sse_events_appear_before_response_finishes_and_wire_bytes_are_unchanged():
    published = []
    async def on_session(session):
        published.append(session.model_copy(deep=True))
    flow = tflow.tflow(resp=True)
    flow.response.headers["content-type"] = "text/event-stream; charset=utf-8"
    addon = InspectorAddon(on_session, max_body_bytes=1024)
    addon._identity = _identity
    await addon.request(flow)
    await addon.responseheaders(flow)
    assert published[-1].is_streaming
    chunks = [b"event: update\r", b"\ndata: {\"msg\":\"selam\"}\r\n", b"id: 42\r\n\r", b"\n"]
    for chunk in chunks:
        assert flow.response.stream(chunk) == chunk
    await asyncio.sleep(0)
    assert next(frame for frame in published[-1].stream.frames if frame.type == "sse").parsed == {
        "event": "update", "data": {"msg": "selam"}, "id": "42",
    }
    assert [frame.raw for frame in published[-1].stream.frames if frame.type == "chunk"] == chunks
    assert published[-1].closed_at is None
    assert published[-1].is_streaming
    await addon.response(flow)
    assert not published[-1].is_streaming
    assert published[-1].response.body.raw == b"".join(chunks)
    assert published[-1].stream.reconstructed == b"".join(chunks)


async def test_sse_capture_limit_keeps_original_output():
    published = []
    async def on_session(session):
        published.append(session.model_copy(deep=True))
    flow = tflow.tflow(resp=True)
    flow.response.headers["content-type"] = "text/event-stream"
    addon = InspectorAddon(on_session, max_body_bytes=10)
    addon._identity = _identity
    await addon.request(flow)
    await addon.responseheaders(flow)
    chunk = b"data: too much\n\n"
    assert flow.response.stream(chunk) == chunk
    await addon.response(flow)
    assert published[-1].response.body.raw == chunk[:10]
    assert published[-1].response.body.size_bytes == len(chunk)
    assert published[-1].is_truncated


async def test_gzip_sse_is_decoded_live_without_altering_wire_bytes():
    published = []
    async def on_session(session):
        published.append(session.model_copy(deep=True))
    flow = tflow.tflow(resp=True)
    flow.response.headers["content-type"] = "text/event-stream"
    flow.response.headers["content-encoding"] = "gzip"
    addon = InspectorAddon(on_session, max_body_bytes=1024)
    addon._identity = _identity
    await addon.request(flow)
    await addon.responseheaders(flow)
    plaintext = b"data: {\"message\":\"selam\"}\n\n"
    compressed = gzip.compress(plaintext)
    assert flow.response.stream(compressed[:7]) == compressed[:7]
    assert flow.response.stream(compressed[7:]) == compressed[7:]
    await asyncio.sleep(0)
    assert next(frame for frame in published[-1].stream.frames if frame.type == "sse").parsed["data"] == {"message": "selam"}
    await addon.response(flow)
    assert published[-1].response.body.raw == compressed
    assert published[-1].stream.reconstructed == plaintext


async def test_chunked_response_preserves_each_chunk_and_full_body():
    published = []
    async def on_session(session):
        published.append(session.model_copy(deep=True))
    flow = tflow.tflow(resp=True)
    flow.response.headers["content-type"] = "application/x-ndjson"
    flow.response.headers["transfer-encoding"] = "chunked"
    addon = InspectorAddon(on_session, max_body_bytes=1024)
    addon._identity = _identity
    await addon.request(flow)
    await addon.responseheaders(flow)
    chunks = [b'{"message":"se', b'lam"}\n']
    for chunk in chunks:
        assert flow.response.stream(chunk) == chunk
    await asyncio.sleep(0)
    assert published[-1].is_streaming
    assert [frame.raw for frame in published[-1].stream.frames] == chunks
    await addon.response(flow)
    assert published[-1].response.body.raw == b"".join(chunks)
    assert published[-1].stream.reconstructed == b"".join(chunks)
    assert not published[-1].is_streaming


async def test_brotli_sse_is_available_after_response_completes():
    published = []
    async def on_session(session):
        published.append(session.model_copy(deep=True))
    flow = tflow.tflow(resp=True)
    flow.response.headers["content-type"] = "text/event-stream"
    flow.response.headers["content-encoding"] = "br"
    addon = InspectorAddon(on_session, max_body_bytes=1024)
    addon._identity = _identity
    await addon.request(flow)
    await addon.responseheaders(flow)
    compressed = brotli.compress(b"data: selam\n\n")
    assert flow.response.stream(compressed) == compressed
    await asyncio.sleep(0)
    assert [frame.raw for frame in published[-1].stream.frames] == [compressed]
    await addon.response(flow)
    assert published[-1].response.body.raw == compressed
    assert next(frame for frame in published[-1].stream.frames if frame.type == "sse").parsed["data"] == "selam"


def test_sse_event_count_is_bounded():
    tracker = SSECapture(1_000_000)
    events = tracker.feed(b"data: x\n\n" * 10_001)
    assert len(events) == 10_000
    assert tracker.truncated


async def test_zstd_request_and_streamed_response_roundtrip_to_plain_recording(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    async def on_session(session):
        recorder.enqueue(session)
    flow = tflow.tflow(resp=True)
    flow.request.timestamp_start = datetime.now(UTC).timestamp()
    request_raw = zstandard.ZstdCompressor(write_content_size=False).compress(
        b'{"message":"selam"}'
    )
    flow.request.content = request_raw
    flow.request.headers["content-type"] = "application/json"
    flow.request.headers["content-encoding"] = "zstd"
    flow.response.headers["content-type"] = "text/event-stream"
    addon = InspectorAddon(on_session, max_body_bytes=1024)
    addon._identity = _identity

    await addon.request(flow)
    await addon.responseheaders(flow)
    chunks = [b'data: {"reply":"me', b'rhaba"}\n\n']
    for chunk in chunks:
        assert flow.response.stream(chunk) == chunk
    await asyncio.sleep(0)
    await addon.response(flow)
    await recorder.stop()

    path = recorder.path(recording_id)
    assert path.suffix == ".jsonl"
    assert b"selam" in path.read_bytes()
    restored = list(read_recording(path))[-1]
    assert restored.request.body.raw == request_raw
    assert restored.request.body.parsed == {"message": "selam"}
    assert restored.response.body.raw == b"".join(chunks)
    assert [frame.raw for frame in restored.stream.frames if frame.type == "chunk"] == chunks
