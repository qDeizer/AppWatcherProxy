from mitmproxy.test import tflow

from backend.capture.addon import InspectorAddon
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
