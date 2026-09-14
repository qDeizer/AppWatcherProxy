from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.cert.manager import CertificateManager
from backend.store.buffer import SessionBuffer
from backend.store.mitm_export import inspect_recording, mitm_chunks
from backend.store.recorder import read_recording

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request) -> dict:
    return {"ok": True, "capture_state": request.app.state.capture.state.value}


@router.get("/stats")
async def stats(request: Request) -> dict:
    store = request.app.state.store
    return {
        "session_count": len(store),
        "memory_bytes": store.memory_bytes,
        "open_connections": request.app.state.capture.open_connections,
        "capture_state": request.app.state.capture.state.value,
        "capture_error": request.app.state.capture.error,
        "recording": request.app.state.recorder.active,
        "recording_error": request.app.state.recorder.error,
        "processing_error": request.app.state.processing_error,
    }


@router.get("/certificate/status")
async def certificate_status() -> dict:
    status = await asyncio.to_thread(CertificateManager().status)
    return {
        "exists": status.exists,
        "subject": status.subject,
        "thumbprint": status.thumbprint,
        "not_after": status.not_after.isoformat() if status.not_after else None,
        "trusted_user": status.trusted_user,
        "trusted_machine": status.trusted_machine,
        "trusted": status.trusted,
    }


@router.get("/applications")
async def applications(request: Request) -> list[dict]:
    return await request.app.state.store.applications()


@router.get("/sessions")
async def sessions(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=500),
) -> dict:
    values = await request.app.state.store.list(limit=limit, offset=offset, query=q)
    total = await request.app.state.store.count(q)
    return {"items": [item.summary() for item in values], "total": total}


@router.get("/sessions/{session_id}")
async def session_detail(session_id: str, request: Request) -> dict:
    session = await request.app.state.store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session bulunamadı")
    return session.model_dump(mode="json")


@router.post("/control/start")
async def start_capture(request: Request) -> dict:
    try:
        await request.app.state.capture.start()
    except RuntimeError as exc:
        await request.app.state.events.publish(
            {"type": "status_change", "state": "error", "error": str(exc)}
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await request.app.state.events.publish({"type": "status_change", "state": "running"})
    return {"state": "running"}


@router.post("/control/stop")
async def stop_capture(request: Request) -> dict:
    await request.app.state.capture.stop()
    await request.app.state.events.publish({"type": "status_change", "state": "stopped"})
    return {"state": "stopped"}


@router.post("/control/clear")
async def clear_sessions(request: Request) -> dict:
    await request.app.state.store.clear()
    await request.app.state.events.publish({"type": "sessions_cleared"})
    return {"cleared": True}


class RecordingOptions(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=1024)
    applications: list[str] = Field(default_factory=list, max_length=1000)
    query: str = Field(default="", max_length=500)


@router.get("/recordings")
async def recordings(request: Request) -> dict:
    recorder = request.app.state.recorder
    return {"items": await asyncio.to_thread(recorder.list), "active": recorder.active,
            "id": recorder.recording_id, "error": recorder.error}


@router.post("/recordings/start")
async def recording_start(options: RecordingOptions, request: Request) -> dict:
    try:
        recording_id = await request.app.state.recorder.start(None, options.applications)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, "Kayıt başlatılamadı; mevcut kaydı durdurup disk izinlerini kontrol edin") from exc
    return {"id": recording_id}


@router.post("/recordings/stop")
async def recording_stop(request: Request) -> dict:
    await request.app.state.recorder.stop()
    return {"stopped": True, "error": request.app.state.recorder.error}


@router.get("/recordings/{recording_id}/download")
async def recording_download(recording_id: str, request: Request):
    try:
        path = request.app.state.recorder.path(recording_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.post("/recordings/{recording_id}/mitm")
async def recording_mitm(recording_id: str, options: RecordingOptions, request: Request):
    try:
        path = request.app.state.recorder.path(recording_id)
        plan = await asyncio.to_thread(inspect_recording, path, options.password)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, "Dışa aktarım açılamadı: parola yanlış, dosya eksik veya bozuk") from exc
    if not plan.supported:
        raise HTTPException(422, f"Replay için tam HTTP/WebSocket oturumu yok; {plan.skipped} oturum atlandı")
    return StreamingResponse(
        mitm_chunks(path, options.password, plan.positions), media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{recording_id}.mitm"',
            "X-Exported-Sessions": str(plan.supported),
            "X-Skipped-Sessions": str(plan.skipped),
            "Cache-Control": "no-store",
        },
    )


@router.post("/recordings/{recording_id}/open")
async def recording_open(recording_id: str, options: RecordingOptions, request: Request) -> dict:
    capture = request.app.state.capture
    recorder = request.app.state.recorder
    async with capture._lock, recorder._lock:
        if capture.state.value not in {"stopped", "error"} or recorder._task is not None:
            raise HTTPException(409, "Kayıt açmadan önce capture ve kaydı durdurun")
        current = request.app.state.store
        replacement = SessionBuffer(current.max_sessions, current.max_bytes)
        def load() -> None:
            async def populate() -> None:
                for session in read_recording(recorder.path(recording_id), options.password):
                    await replacement.upsert(session)
            asyncio.run(populate())
        try:
            await asyncio.to_thread(load)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, "Kayıt açılamadı: parola yanlış, dosya eksik veya bozuk. Mevcut RAM verisi korundu.") from exc
        request.app.state.store = replacement
    await request.app.state.events.publish({"type": "sessions_cleared"})
    return {"loaded": len(replacement)}


@router.post("/recordings/export")
async def recording_export(options: RecordingOptions, request: Request) -> dict:
    from backend.store.recorder import Recorder

    store = request.app.state.store
    sessions = await store.list(limit=store.max_sessions, query=options.query)
    recorder = Recorder(request.app.state.recorder.root)
    recording_id = await recorder.start(None, options.applications)
    try:
        for session in reversed(sessions):
            if options.applications and session.application.name not in options.applications:
                continue
            data = session.model_dump_json().encode("utf-8")
            await asyncio.to_thread(recorder._writer.append, data)
    except Exception as exc:
        recorder.error = "Dışa aktarım tamamlanamadı"
        raise HTTPException(500, "Dışa aktarım başarısız; disk alanını ve izinleri kontrol edin") from exc
    finally:
        await recorder.stop()
    if recorder.error:
        raise HTTPException(500, recorder.error)
    return {"id": recording_id}
