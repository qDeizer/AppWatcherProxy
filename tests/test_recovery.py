from backend.net import recovery
from backend.net.recovery import process_is_alive


def test_process_is_alive_rejects_missing_pid() -> None:
    assert not process_is_alive(None)
    assert not process_is_alive(0)


def test_cleanup_does_not_erase_new_live_instance_state(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime"
    recovery.write_runtime_state(runtime_dir, {
        "main_pid": 42, "main_started_at": 123.0,
    })
    monkeypatch.setattr(recovery, "process_is_alive", lambda *_: True)
    monkeypatch.setattr(recovery, "remove_quic_rule", lambda: None)
    result = recovery.cleanup_stale_state(runtime_dir)
    assert result["skipped_live"] is True
    assert recovery.read_runtime_state(runtime_dir)["main_pid"] == 42


def test_cleanup_removes_only_stale_state(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime"
    recovery.write_runtime_state(runtime_dir, {
        "main_pid": 42, "main_started_at": 123.0,
    })
    monkeypatch.setattr(recovery, "process_is_alive", lambda *_: False)
    monkeypatch.setattr(recovery, "remove_quic_rule", lambda: True)
    result = recovery.cleanup_stale_state(runtime_dir)
    assert result["quic_rule_removed"] is True
    assert not (runtime_dir / "state.json").exists()
