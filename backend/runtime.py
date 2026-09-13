from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil

from backend.net.recovery import write_runtime_state


class Watchdog:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        flags = 0
        if os.name == "nt":
            # Keep the watchdog outside the console process group so Ctrl+C,
            # console close and taskkill of the main PID cannot kill both.
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "backend.net.watchdog",
                "--parent-pid",
                str(os.getpid()),
                "--runtime-dir",
                str(self.runtime_dir),
            ],
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        write_runtime_state(
            self.runtime_dir,
            {
                "main_pid": os.getpid(),
                "main_started_at": psutil.Process(os.getpid()).create_time(),
                "watchdog_pid": self.process.pid,
                "quic_blocked": False,
            },
        )

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None
