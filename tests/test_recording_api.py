from io import BytesIO
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mitmproxy.io import FlowReader

from backend.api.routes import router
from backend.capture.engine import CaptureEngine, CaptureState
from backend.events import EventBus
from backend.store.buffer import SessionBuffer
from backend.store.model import (
    ApplicationInfo,
    Connection,
    Payload,
    Request,
    Response,
    Session,
)
from backend.store.recorder import Recorder


async def test_recording_api_roundtrip_and_safe_failed_import(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.store = SessionBuffer(100, 1_000_000)
    app.state.events = EventBus()
    app.state.capture = CaptureEngine(None, 1024)
    app.state.recorder = Recorder(tmp_path)
    app.state.processing_error = None
    session = Session(connection_id="qa", type="tcp", connection=Connection(),
                      application=ApplicationInfo(name="qa.exe"), error="selam")
    await app.state.store.upsert(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        options = {"password": "qa-password", "applications": ["qa.exe"], "query": "selam"}
        exported = await client.post("/api/recordings/export", json=options)
        assert exported.status_code == 200
        recording_id = exported.json()["id"]
        download = await client.get(f"/api/recordings/{recording_id}/download")
        assert download.content.startswith(b"AWP1")
        assert b"selam" not in download.content
        wrong = await client.post(f"/api/recordings/{recording_id}/open", json={"password": "wrong-password"})
        assert wrong.status_code == 400
        assert len(app.state.store) == 1
        app.state.capture.state = CaptureState.RUNNING
        blocked = await client.post(f"/api/recordings/{recording_id}/open", json=options)
        assert blocked.status_code == 409
        app.state.capture.state = CaptureState.STOPPED
        await client.post("/api/control/clear")
        opened = await client.post(f"/api/recordings/{recording_id}/open", json=options)
        assert opened.json() == {"loaded": 1}
        found = await client.get("/api/sessions", params={"q": "selam"})
        assert found.json()["total"] == 1
        started = await client.post("/api/recordings/start", json=options)
        assert started.status_code == 200
        assert (await client.get("/api/stats")).json()["recording"]
        await client.post("/api/recordings/stop")
        assert not (await client.get("/api/stats")).json()["recording"]


async def test_failed_capture_task_is_visible():
    import asyncio

    capture = CaptureEngine(None, 1024)
    capture.state = CaptureState.RUNNING
    async def fail():
        raise RuntimeError("sensitive text must not enter diagnostics")
    task = asyncio.create_task(fail())
    await asyncio.sleep(0)
    capture._finished(task)
    assert capture.state == CaptureState.ERROR
    assert "RuntimeError" in capture.error
    assert "sensitive" not in capture.error
    capture._master = SimpleNamespace(shutdown=lambda: None)
    capture._task = task
    await capture.stop()
    assert capture.state == CaptureState.STOPPED


async def test_mitm_api_warns_about_skipped_sessions_and_rejects_wrong_password(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.store = SessionBuffer(100, 1_000_000)
    app.state.events = EventBus()
    app.state.capture = CaptureEngine(None, 1024)
    app.state.recorder = Recorder(tmp_path)
    app.state.processing_error = None
    await app.state.store.upsert(Session(
        connection_id="http", type="http", connection=Connection(),
        request=Request(method="GET", scheme="https", host="example.test", port=443, path="/events"),
        response=Response(status_code=200, body=Payload(raw=b"data: hi\n\n", size_bytes=10)),
    ))
    await app.state.store.upsert(Session(connection_id="tcp", type="tcp", connection=Connection()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        exported = await client.post("/api/recordings/export", json={"password": "api-password"})
        recording_id = exported.json()["id"]
        bad = await client.post(f"/api/recordings/{recording_id}/mitm", json={"password": "wrong-password"})
        assert bad.status_code == 400
        result = await client.post(f"/api/recordings/{recording_id}/mitm", json={"password": "api-password"})
        assert result.status_code == 200
        assert result.headers["x-exported-sessions"] == "1"
        assert result.headers["x-skipped-sessions"] == "1"
        assert result.headers["cache-control"] == "no-store"
        flows = list(FlowReader(BytesIO(result.content)).stream())
        assert len(flows) == 1
        assert flows[0].response.raw_content == b"data: hi\n\n"
