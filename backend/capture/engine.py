from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum

from backend.capture.addon import InspectorAddon
from backend.diagnostics import report_exception
from backend.store.model import Session


class CaptureState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class CaptureEngine:
    def __init__(
        self,
        on_session: Callable[[Session], Awaitable[None]],
        max_body_bytes: int,
    ) -> None:
        self.state = CaptureState.STOPPED
        self.error: str | None = None
        self._on_session = on_session
        self._max_body_bytes = max_body_bytes
        self._master = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._addon = None

    @property
    def open_connections(self) -> int:
        return len(self._addon.connections) if self._addon else 0

    def _finished(self, task: asyncio.Task) -> None:
        if self.state in {CaptureState.STOPPED, CaptureState.STOPPING}:
            return
        exception = None if task.cancelled() else task.exception()
        self.error = f"Capture görevi durdu ({type(exception).__name__ if exception else 'unexpected exit'}). Yeniden başlatabilirsiniz."
        self.state = CaptureState.ERROR
        if exception:
            report_exception("capture_task_failed", exception)

    async def start(self) -> None:
        async with self._lock:
            if self.state in {CaptureState.STARTING, CaptureState.RUNNING}:
                return
            self.state = CaptureState.STARTING
            self.error = None
            try:
                from mitmproxy import options
                from backend.capture.master import EmbeddedMaster

                opts = options.Options(mode=["local"])
                self._master = EmbeddedMaster(opts, with_termlog=False, with_dumper=False)
                self._addon = InspectorAddon(self._on_session, self._max_body_bytes)
                self._master.addons.add(self._addon)
                self._task = asyncio.create_task(self._master.run())
                self._task.add_done_callback(self._finished)
                ready = asyncio.create_task(self._master.ready.wait())
                try:
                    completed, _ = await asyncio.wait(
                        {ready, self._task}, timeout=30, return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not completed:
                        self._master.shutdown()
                        self._task.cancel()
                        await asyncio.gather(self._task, return_exceptions=True)
                        raise RuntimeError("Capture başlangıcı zaman aşımına uğradı")
                finally:
                    ready.cancel()
                    await asyncio.gather(ready, return_exceptions=True)
                if self._task.done():
                    await self._task
                    raise RuntimeError("Capture görevi başlangıçta sonlandı")
                self.state = CaptureState.RUNNING
            except asyncio.CancelledError:
                if self._master is not None:
                    self._master.shutdown()
                if self._task is not None:
                    self._task.cancel()
                    await asyncio.gather(self._task, return_exceptions=True)
                self._master = None
                self._task = None
                self._addon = None
                self.state = CaptureState.STOPPED
                raise
            except Exception as exc:
                self.error = str(exc)
                self.state = CaptureState.ERROR
                self._master = None
                self._task = None
                raise RuntimeError(f"Capture başlatılamadı: {exc}") from exc

    async def stop(self) -> None:
        async with self._lock:
            if self.state == CaptureState.STOPPED:
                return
            self.state = CaptureState.STOPPING
            if self._master is not None:
                self._master.shutdown()
            if self._task is not None:
                try:
                    await asyncio.wait_for(self._task, timeout=10)
                except (TimeoutError, asyncio.CancelledError):
                    self._task.cancel()
                except Exception as exc:  # noqa: BLE001 — cleanup must survive a failed capture task
                    report_exception("capture_stop_failed", exc)
            self._master = None
            self._task = None
            self._addon = None
            self.state = CaptureState.STOPPED
            self.error = None
