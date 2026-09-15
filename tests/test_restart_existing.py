from types import SimpleNamespace

import psutil
import pytest

from backend.net import restart_existing


class FakeProcess:
    def __init__(self, pid: int, cwd: str) -> None:
        self.pid = pid
        self.working_directory = cwd
        self.terminated = False
        self.waited = False

    def cmdline(self) -> list[str]:
        return ["python.exe", "-m", "backend.main"]

    def cwd(self) -> str:
        return self.working_directory

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int) -> None:
        assert timeout == 10
        self.waited = True


def test_restart_stops_recording_and_capture_before_terminating(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime"
    process = FakeProcess(42, str(tmp_path))
    watchdog = FakeProcess(43, str(tmp_path))
    watchdog.cmdline = lambda: ["python.exe", "-m", "backend.net.watchdog"]
    actions = []
    monkeypatch.setattr(restart_existing, "read_runtime_state", lambda _: {
        "main_pid": 42, "main_started_at": 123.0, "watchdog_pid": 43,
    })
    monkeypatch.setattr(restart_existing, "process_is_alive", lambda *_: True)
    monkeypatch.setattr(psutil, "Process", lambda pid: process if pid == 42 else watchdog)
    monkeypatch.setattr(psutil, "net_connections", lambda **_: [SimpleNamespace(
        pid=42, status=psutil.CONN_LISTEN,
        laddr=SimpleNamespace(port=restart_existing.settings.port),
    )])
    def post(path):
        actions.append(path)
        return {"stopped": True} if path.endswith("/stop") and "recordings" in path else {"state": "stopped"}
    monkeypatch.setattr(restart_existing, "_post", post)

    assert restart_existing.stop_existing(runtime_dir)
    assert actions == ["/api/recordings/stop", "/api/control/stop"]
    assert process.terminated and process.waited
    assert watchdog.waited


def test_restart_refuses_unrelated_process(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime"
    process = FakeProcess(42, str(tmp_path / "another-project"))
    monkeypatch.setattr(restart_existing, "read_runtime_state", lambda _: {
        "main_pid": 42, "main_started_at": 123.0,
    })
    monkeypatch.setattr(restart_existing, "process_is_alive", lambda *_: True)
    monkeypatch.setattr(psutil, "Process", lambda _: process)
    with pytest.raises(RuntimeError, match="doğrulanamadı"):
        restart_existing.stop_existing(runtime_dir)
    assert not process.terminated


def test_restart_does_nothing_with_stale_state(tmp_path, monkeypatch):
    monkeypatch.setattr(restart_existing, "read_runtime_state", lambda _: {
        "main_pid": 42, "main_started_at": 123.0,
    })
    monkeypatch.setattr(restart_existing, "process_is_alive", lambda *_: False)
    assert not restart_existing.stop_existing(tmp_path / ".runtime")


def test_restart_keeps_process_if_capture_stop_fails(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime"
    process = FakeProcess(42, str(tmp_path))
    monkeypatch.setattr(restart_existing, "read_runtime_state", lambda _: {
        "main_pid": 42, "main_started_at": 123.0,
    })
    monkeypatch.setattr(restart_existing, "process_is_alive", lambda *_: True)
    monkeypatch.setattr(psutil, "Process", lambda _: process)
    monkeypatch.setattr(psutil, "net_connections", lambda **_: [SimpleNamespace(
        pid=42, status=psutil.CONN_LISTEN,
        laddr=SimpleNamespace(port=restart_existing.settings.port),
    )])
    monkeypatch.setattr(restart_existing, "_post", lambda path: (
        {"stopped": True} if "recordings" in path else {"state": "error"}
    ))
    with pytest.raises(RuntimeError, match="güvenli"):
        restart_existing.stop_existing(runtime_dir)
    assert not process.terminated
