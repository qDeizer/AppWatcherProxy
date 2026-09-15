from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

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
from backend.store.recorder import END_MARKER, Recorder, RecordingWriter


async def test_export_rotates_segments_and_all_are_readable(tmp_path, monkeypatch):
    from backend.store import recorder as module
    monkeypatch.setattr(module, "MAX_FILE", 1600)
    app = FastAPI()
    app.include_router(router)
    app.state.store = SessionBuffer(100, 1_000_000)
    app.state.recorder = Recorder(tmp_path)
    sessions = [Session(connection_id="test", type="tcp", connection=Connection()) for _ in range(5)]
    for session in sessions:
        await app.state.store.upsert(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/recordings/export", json={})
    assert result.status_code == 200
    ids = result.json()["ids"]
    assert len(ids) > 1
    restored = [s for rid in ids for s in module.read_recording(tmp_path / f"{rid}.jsonl")]
    assert {s.id for s in restored} == {s.id for s in sessions}


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
        options = {"applications": ["qa.exe"], "query": "selam"}
        exported = await client.post("/api/recordings/export", json=options)
        assert exported.status_code == 200
        recording_id = exported.json()["id"]
        download = await client.get(f"/api/recordings/{recording_id}/download")
        assert download.content.startswith(b"{")
        assert b"selam" in download.content
        listed = (await client.get("/api/recordings")).json()
        assert listed["default_format"] == "jsonl"
        assert listed["items"][0]["password_required"] is False
        assert (await client.get("/api/stats")).json()["recording_format"] == "jsonl"
        path = tmp_path / f"{recording_id}.jsonl"
        path.write_bytes(download.content[:-1])
        damaged = await client.post(f"/api/recordings/{recording_id}/open", json={})
        assert damaged.status_code == 400
        assert len(app.state.store) == 1
        path.write_bytes(download.content)
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
        exported = await client.post("/api/recordings/export", json={})
        recording_id = exported.json()["id"]
        result = await client.post(f"/api/recordings/{recording_id}/mitm", json={})
        assert result.status_code == 200
        assert result.headers["x-exported-sessions"] == "1"
        assert result.headers["x-skipped-sessions"] == "1"
        assert result.headers["cache-control"] == "no-store"
        flows = list(FlowReader(BytesIO(result.content)).stream())
        assert len(flows) == 1
        assert flows[0].response.raw_content == b"data: hi\n\n"

        old_id = uuid4().hex
        writer = RecordingWriter(tmp_path / f"{old_id}.awp", "old-password")
        old_session = (await app.state.store.list())[-1]
        old_session.opened_at = datetime.now(UTC)
        writer.append(old_session.model_dump_json().encode())
        writer.append(END_MARKER)
        writer.close()
        legacy = (await client.get("/api/recordings")).json()["items"]
        assert next(item for item in legacy if item["id"] == old_id)["password_required"] is True
        converted = await client.post(f"/api/recordings/{old_id}/plain", json={"password": "old-password"})
        assert converted.status_code == 200
        assert converted.json()["recovered_incomplete"] is False
        assert (tmp_path / f"{converted.json()['ids'][0]}.jsonl").is_file()
        wrong = await client.post(f"/api/recordings/{old_id}/mitm", json={"password": "wrong-password"})
        assert wrong.status_code == 400
        unlocked = await client.post(f"/api/recordings/{old_id}/mitm", json={"password": "old-password"})
        assert unlocked.status_code == 200
