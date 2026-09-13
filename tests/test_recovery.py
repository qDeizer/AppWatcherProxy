from backend.net.recovery import process_is_alive


def test_process_is_alive_rejects_missing_pid() -> None:
    assert not process_is_alive(None)
    assert not process_is_alive(0)

