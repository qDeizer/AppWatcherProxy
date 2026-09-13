from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router as api_router
from backend.api.websocket import router as websocket_router
from backend.capture.engine import CaptureEngine
from backend.config import settings
from backend.diagnostics import configure_diagnostics, report_exception
from backend.events import EventBus
from backend.net.recovery import (
    cleanup_stale_state,
    process_is_alive,
    read_runtime_state,
    verify_network_configuration,
)
from backend.runtime import Watchdog
from backend.store.buffer import SessionBuffer
from backend.store.model import Session
from backend.store.recorder import Recorder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("network-inspector")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_diagnostics(settings.runtime_dir)
    previous_state = read_runtime_state(settings.runtime_dir)
    previous_pid = previous_state.get("main_pid")
    if process_is_alive(previous_pid, previous_state.get("main_started_at")):
        raise RuntimeError(
            f"Network Inspector zaten çalışıyor (PID {previous_pid}). "
            "İkinci instance başlatılmadı."
        )
    cleanup = cleanup_stale_state(settings.runtime_dir)
    LOGGER.info("Startup recovery: %s", cleanup)
    store = SessionBuffer(settings.max_sessions, settings.max_memory_bytes)
    events = EventBus()
    recorder = Recorder(settings.runtime_dir.parent / "recordings")

    async def on_session(session: Session) -> None:
        store = app.state.store
        existing = await store.get(session.id)
        try:
            evicted = await store.upsert(session)
            recorder.enqueue(session)
            if app.state.capture._addon:
                app.state.capture._addon.discard(evicted)
        except Exception as exc:  # noqa: BLE001 — isolate malformed traffic from the capture task
            report_exception("session_processing_failed", exc)
            app.state.processing_error = f"Bir oturum işlenemedi ({type(exc).__name__}). diagnostics.log dosyasına bakın."
            return
        await events.publish(
            {
                "type": "session_update" if existing else "session_new",
                "session": session.summary(),
            }
        )

    app.state.store = store
    app.state.events = events
    app.state.recorder = recorder
    app.state.processing_error = None
    app.state.capture = CaptureEngine(on_session, settings.max_body_bytes)
    watchdog = Watchdog(settings.runtime_dir)
    watchdog.start()
    try:
        yield
    finally:
        LOGGER.info("Safe shutdown started")
        try:
            await app.state.capture.stop()
        finally:
            try:
                await recorder.stop()
            finally:
                watchdog.stop()
                cleanup_stale_state(settings.runtime_dir)
                LOGGER.info("Shutdown complete; proxy_check_ok=%s", verify_network_configuration().get("proxy_check_ok"))


app = FastAPI(title="Network Inspector", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(websocket_router)

assets = settings.frontend_dist / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str):
    index = settings.frontend_dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse(
        "<h1>Network Inspector</h1><p>Frontend build bulunamadı. "
        "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>",
        status_code=503,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=False)
