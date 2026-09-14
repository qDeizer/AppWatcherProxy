from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.capture.engine import CaptureEngine
from backend.config import settings
from backend.events import EventBus
from backend.store.buffer import SessionBuffer
from backend.store.recorder import Recorder


with TemporaryDirectory(prefix="network-inspector-qa-") as temporary:
    app = FastAPI()
    app.include_router(router)
    app.state.store = SessionBuffer(100, 1_000_000)
    app.state.events = EventBus()
    app.state.recorder = Recorder(Path(temporary) / "recordings")
    app.state.capture = CaptureEngine(None, settings.max_body_bytes)
    app.state.processing_error = None
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        return FileResponse(settings.frontend_dist / "index.html")

    uvicorn.run(app, host="127.0.0.1", port=43111)
