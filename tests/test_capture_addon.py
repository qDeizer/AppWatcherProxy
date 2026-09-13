import asyncio
import gzip

import brotli
from mitmproxy.test import tflow

from backend.capture.addon import InspectorAddon
from backend.capture.sse import SSECapture
from backend.store.model import ApplicationInfo, ProcessInfo


def _identity(_flow):
    return ApplicationInfo(name="test.exe"), ProcessInfo(pid=123, name="test.exe")


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
    assert published[-1].stream.frames[0].parsed == {
        "event": "update", "data": {"msg": "selam"}, "id": "42",
    }
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
    assert published[-1].stream.frames[0].parsed["data"] == {"message": "selam"}
    await addon.response(flow)
    assert published[-1].response.body.raw == compressed
    assert published[-1].stream.reconstructed == plaintext


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
    assert published[-1].stream.frames == []
    await addon.response(flow)
    assert published[-1].response.body.raw == compressed
    assert published[-1].stream.frames[0].parsed["data"] == "selam"


def test_sse_event_count_is_bounded():
    tracker = SSECapture(1_000_000)
    events = tracker.feed(b"data: x\n\n" * 10_001)
    assert len(events) == 10_000
    assert tracker.truncated
