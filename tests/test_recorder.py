from datetime import UTC, datetime, timedelta

import pytest

from backend.store.model import ApplicationInfo, Connection, Frame, Session, Stream
from backend.store.recorder import Recorder, read_recording


def sample(name="chosen.exe", raw=b"selam\xff\x00"):
    return Session(
        connection_id="test", type="websocket", application=ApplicationInfo(name=name),
        connection=Connection(), stream=Stream(kind="websocket", reconstructed=raw,
        frames=[Frame(seq=0, direction="up", size_bytes=len(raw), type="binary", raw=raw)]),
    )


async def test_recording_off_writes_nothing(tmp_path):
    root = tmp_path / "recordings"
    recorder = Recorder(root)
    recorder.enqueue(sample())
    await recorder.stop()
    assert not root.exists()


async def test_encrypted_recording_filters_and_preserves_binary(tmp_path):
    recorder = Recorder(tmp_path)
    old = sample()
    old.opened_at = datetime.now(UTC) - timedelta(days=1)
    recording_id = await recorder.start("long-password", ["chosen.exe"])
    recorder.enqueue(old)
    recorder.enqueue(sample("other.exe"))
    session = sample()
    recorder.enqueue(session)
    session.stream.reconstructed = b"changed"
    await recorder.stop()
    path = recorder.path(recording_id)
    assert b"selam" not in path.read_bytes()
    restored = list(read_recording(path, "long-password"))
    assert len(restored) == 1
    assert restored[0].stream.reconstructed == b"selam\xff\x00"
    assert restored[0].stream.frames[0].raw == b"selam\xff\x00"
    with pytest.raises(ValueError, match="Parola"):
        list(read_recording(path, "wrong-password"))


async def test_truncation_and_tampering_are_rejected(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start("long-password", [])
    recorder.enqueue(sample())
    await recorder.stop()
    path = recorder.path(recording_id)
    data = path.read_bytes()
    path.write_bytes(data[:-1])
    with pytest.raises(ValueError):
        list(read_recording(path, "long-password"))
    changed = bytearray(data)
    changed[40] ^= 1
    path.write_bytes(changed)
    with pytest.raises(ValueError):
        list(read_recording(path, "long-password"))


async def test_disk_failure_is_visible_and_capture_can_continue(tmp_path, monkeypatch):
    recorder = Recorder(tmp_path)
    await recorder.start("long-password", [])
    def fail(data):
        raise OSError("disk full")
    monkeypatch.setattr(recorder._writer, "append", fail)
    recorder.enqueue(sample())
    await recorder.stop()
    assert not recorder.active
    assert recorder.error
    await recorder.start("long-password", [])
    await recorder.stop()


async def test_path_and_double_start_are_rejected(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start("long-password", [])
    with pytest.raises(ValueError):
        recorder.path(recording_id)
    with pytest.raises(ValueError):
        await recorder.start("long-password", [])
    with pytest.raises(ValueError):
        recorder.path("../passwords")
    await recorder.stop()


async def test_passwordless_recording_uses_windows_account_and_rejects_tampering(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    recorder.enqueue(sample())
    await recorder.stop()
    path = recorder.path(recording_id)
    assert path.read_bytes().startswith(b"AWP2")
    assert recorder.list()[0]["password_required"] is False
    assert next(read_recording(path)).stream.reconstructed == b"selam\xff\x00"
    changed = bytearray(path.read_bytes())
    changed[-20] ^= 1
    path.write_bytes(changed)
    with pytest.raises(ValueError):
        list(read_recording(path))
