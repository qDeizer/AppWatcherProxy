from io import BytesIO

from mitmproxy.io import FlowReader
from wsproto.frame_protocol import Opcode

from backend.store.mitm_export import inspect_recording, mitm_chunks
from backend.store.model import (
    ApplicationInfo,
    Connection,
    Frame,
    Header,
    Payload,
    Request,
    Response,
    Session,
    Stream,
)
from backend.store.recorder import Recorder


async def test_plain_recording_mitm_is_readable_and_preserves_captured_body(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    body = b"\x00selam\xff"
    session = Session(
        connection_id="test", type="http", application=ApplicationInfo(name="test.exe"),
        connection=Connection(),
        request=Request(method="POST", scheme="https", host="example.test", port=443,
                        path="/api?q=1", headers=[Header(name="content-type", value="application/octet-stream")],
                        body=Payload(raw=body, size_bytes=len(body))),
        response=Response(status_code=201, headers=[Header(name="content-type", value="text/plain")],
                          body=Payload(raw=b"ok", size_bytes=2)),
    )
    recorder.enqueue(session)
    session.response.body.raw = b"latest"
    recorder.enqueue(session)
    await recorder.stop()
    path = recorder.path(recording_id)
    plan = inspect_recording(path)
    assert (plan.supported, plan.skipped) == (1, 0)
    flows = list(FlowReader(BytesIO(b"".join(mitm_chunks(path)))).stream())
    assert len(flows) == 1
    assert flows[0].request.url == "https://example.test/api?q=1"
    assert flows[0].request.raw_content == body
    assert flows[0].response.raw_content == b"latest"
    assert flows[0].response.status_code == 201


async def test_websocket_frames_roundtrip_through_mitm(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    session = Session(
        connection_id="ws", type="websocket", connection=Connection(),
        request=Request(method="GET", scheme="https", host="example.test", port=443, path="/ws"),
        response=Response(status_code=101),
        stream=Stream(kind="websocket", frames=[
            Frame(seq=0, direction="up", size_bytes=5, type="text", raw=b"hello"),
            Frame(seq=1, direction="down", size_bytes=2, type="binary", raw=b"\x00\xff"),
            Frame(seq=2, direction="down", size_bytes=0, type="ping", raw=b""),
        ]),
    )
    recorder.enqueue(session)
    await recorder.stop()
    flow = next(FlowReader(BytesIO(b"".join(mitm_chunks(recorder.path(recording_id))))).stream())
    assert [message.type for message in flow.websocket.messages] == [Opcode.TEXT, Opcode.BINARY, Opcode.PING]
    assert [message.content for message in flow.websocket.messages] == [b"hello", b"\x00\xff", b""]
