from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import psutil

from backend.config import settings
from backend.net.recovery import process_is_alive, read_runtime_state


def _post(path: str) -> dict:
    request = urllib.request.Request(
        f"http://{settings.host}:{settings.port}{path}", method="POST"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _matches_project(process: psutil.Process, runtime_dir: Path) -> bool:
    command = [argument.casefold() for argument in process.cmdline()]
    if "backend.main" not in command:
        return False
    if Path(process.cwd()).resolve() != runtime_dir.parent.resolve():
        return False
    return any(
        connection.pid == process.pid
        and connection.status == psutil.CONN_LISTEN
        and connection.laddr.port == settings.port
        for connection in psutil.net_connections(kind="tcp")
        if connection.laddr
    )


def stop_existing(runtime_dir: Path) -> bool:
    state = read_runtime_state(runtime_dir)
    pid = state.get("main_pid")
    started_at = state.get("main_started_at")
    if not process_is_alive(pid, started_at):
        return False
    process = psutil.Process(pid)
    if not _matches_project(process, runtime_dir):
        raise RuntimeError("Çalışan PID bu projeye ait doğrulanamadı; otomatik kapatılmadı")

    stopped_recording = _post("/api/recordings/stop")
    stopped_capture = _post("/api/control/stop")
    if not stopped_recording.get("stopped") or stopped_capture.get("state") != "stopped":
        raise RuntimeError("Çalışan örnek güvenli biçimde durdurulamadı")
    process.terminate()
    process.wait(timeout=10)
    watchdog_pid = state.get("watchdog_pid")
    if watchdog_pid:
        try:
            watchdog = psutil.Process(watchdog_pid)
            if "backend.net.watchdog" in [arg.casefold() for arg in watchdog.cmdline()]:
                # Its cleanup must finish before a new backend writes state.json.
                watchdog.wait(timeout=10)
        except psutil.NoSuchProcess:
            pass
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        stopped = stop_existing(args.runtime_dir)
    except (OSError, RuntimeError, ValueError, psutil.Error) as exc:
        print(f"Yeniden başlatma güvenli biçimde tamamlanamadı: {type(exc).__name__}: {exc}")
        return 1
    print("Önceki Network Inspector güvenle durduruldu." if stopped else "Çalışan örnek yok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
