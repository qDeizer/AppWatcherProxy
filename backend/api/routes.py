from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from backend.cert.manager import CertificateManager

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
        "open_connections": 0,
        "capture_state": request.app.state.capture.state.value,
        "capture_error": request.app.state.capture.error,
        "recording": False,
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
