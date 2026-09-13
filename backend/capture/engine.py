from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum

from backend.capture.addon import InspectorAddon
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

    async def start(self) -> None:
        async with self._lock:
            if self.state in {CaptureState.STARTING, CaptureState.RUNNING}:
                return
            self.state = CaptureState.STARTING
            self.error = None
            try:
                from mitmproxy import options
                from mitmproxy.tools.dump import DumpMaster

                opts = options.Options(mode=["local"])
                self._master = DumpMaster(opts, with_termlog=False, with_dumper=False)
                self._master.addons.add(
                    InspectorAddon(self._on_session, self._max_body_bytes)
                )
                self._task = asyncio.create_task(self._master.run())
                await asyncio.sleep(0)
                if self._task.done():
                    await self._task
                self.state = CaptureState.RUNNING
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
            self._master = None
            self._task = None
            self.state = CaptureState.STOPPED
            self.error = None

