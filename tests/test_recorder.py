from datetime import UTC, datetime, timedelta

import pytest

from backend.store import recorder as recorder_module
from backend.store.model import ApplicationInfo, Connection, Frame, Session, Stream
from backend.store.recorder import (
    END_MARKER,
    Recorder,
    RecordingWriter,
    convert_to_plain,
    read_recording,
)


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


async def test_unreadable_legacy_file_does_not_hide_other_recordings(tmp_path, monkeypatch):
    from pathlib import Path
    recorder = Recorder(tmp_path)
    rid = await recorder.start(None, [])
    await recorder.stop()
    locked = tmp_path / ("f" * 32 + ".awp")
    locked.write_bytes(b"AWP1")
    original = Path.open
    def open_file(path, *args, **kwargs):
        if path == locked:
            raise PermissionError("file locked")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    assert [item["id"] for item in recorder.list()] == [rid]


async def test_plain_recording_filters_and_preserves_binary(tmp_path):
    recorder = Recorder(tmp_path)
    old = sample()
    old.opened_at = datetime.now(UTC) - timedelta(days=1)
    recording_id = await recorder.start(None, ["chosen.exe"])
    recorder.enqueue(sample("other.exe"))
    session = sample()
    recorder.enqueue(session)
    session.stream.reconstructed = b"changed"
    await recorder.stop()
    path = recorder.path(recording_id)
    assert path.suffix == ".jsonl"
    assert b'"type":"websocket"' in path.read_bytes()
    restored = list(read_recording(path))
    assert len(restored) == 1
    assert restored[0].stream.reconstructed == b"selam\xff\x00"
    assert restored[0].stream.frames[0].raw == b"selam\xff\x00"


async def test_live_update_of_preexisting_connection_is_recorded(tmp_path):
    session = sample()
    session.opened_at = datetime.now(UTC) - timedelta(days=1)
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    session.stream.reconstructed = b"new message on existing connection"
    recorder.enqueue(session)
    await recorder.stop()
    restored = list(read_recording(recorder.path(recording_id)))
    assert restored[0].stream.reconstructed == session.stream.reconstructed


async def test_cancelled_stop_request_does_not_cancel_disk_writer(tmp_path, monkeypatch):
    import asyncio
    import threading
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    entered = threading.Event()
    release = threading.Event()
    original = recorder._write_batch
    def slow_write(batch):
        entered.set()
        release.wait(5)
        original(batch)
    monkeypatch.setattr(recorder, "_write_batch", slow_write)
    recorder.enqueue(sample())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        stop = asyncio.create_task(recorder.stop())
        await asyncio.sleep(0)
        stop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stop
        assert not recorder._task.cancelled()
    finally:
        release.set()
    await asyncio.wait_for(recorder.stop(), 5)
    assert len(list(read_recording(recorder.path(recording_id)))) == 1


def test_old_encrypted_recordings_remain_readable(tmp_path):
    path = tmp_path / "0123456789abcdef0123456789abcdef.awp"
    writer = RecordingWriter(path, "long-password")
    writer.append(sample().model_dump_json().encode())
    writer.append(END_MARKER)
    writer.close()
    assert len(list(read_recording(path, "long-password"))) == 1
    with pytest.raises(ValueError, match="Parola"):
        list(read_recording(path, "wrong-password"))
    ids, incomplete = convert_to_plain(path, tmp_path, "long-password")
    assert len(ids) == 1
    assert not incomplete
    plain = tmp_path / f"{ids[0]}.jsonl"
    assert len(list(read_recording(plain))) == 1
    assert path.exists()


def test_incomplete_legacy_recording_recovers_authenticated_prefix(tmp_path):
    path = tmp_path / "0123456789abcdef0123456789abcdef.awp"
    writer = RecordingWriter(path, "long-password")
    original = sample()
    writer.append(original.model_dump_json().encode())
    writer.close()
    ids, incomplete = convert_to_plain(path, tmp_path, "long-password")
    assert incomplete
    assert [item.id for item in read_recording(tmp_path / f"{ids[0]}.jsonl")] == [original.id]
    assert path.exists()


async def test_truncation_and_tampering_are_rejected(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    recorder.enqueue(sample())
    await recorder.stop()
    path = recorder.path(recording_id)
    data = path.read_bytes()
    path.write_bytes(data[:-1])
    with pytest.raises(ValueError):
        list(read_recording(path))
    path.write_bytes(b"garbage\n" + data)
    with pytest.raises(ValueError):
        list(read_recording(path))


async def test_disk_failure_is_visible_and_capture_can_continue(tmp_path, monkeypatch):
    recorder = Recorder(tmp_path)
    await recorder.start(None, [])
    def fail(data):
        raise OSError("disk full")
    monkeypatch.setattr(recorder._writer, "append", fail)
    recorder.enqueue(sample())
    await recorder.stop()
    assert not recorder.active
    assert recorder.error
    await recorder.start(None, [])
    await recorder.stop()


async def test_path_and_double_start_are_rejected(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    with pytest.raises(ValueError):
        recorder.path(recording_id)
    with pytest.raises(ValueError):
        await recorder.start(None, [])
    with pytest.raises(ValueError):
        recorder.path("../passwords")
    await recorder.stop()


async def test_plain_recording_is_readable_without_windows_account(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    recorder.enqueue(sample())
    await recorder.stop()
    path = recorder.path(recording_id)
    assert path.suffix == ".jsonl"
    assert path.read_bytes().startswith(b"{")
    assert recorder.list()[0]["password_required"] is False
    assert recorder.list()[0]["encrypted"] is False
    assert next(read_recording(path)).stream.reconstructed == b"selam\xff\x00"


async def test_full_recording_segment_rolls_over_without_losing_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder_module, "MAX_FILE", 2_000)
    recorder = Recorder(tmp_path)
    first_id = await recorder.start(None, [])
    sessions = [sample() for _ in range(3)]
    for session in sessions:
        recorder.enqueue(session)
    await recorder.stop()

    paths = sorted(tmp_path.glob("*.jsonl"))
    assert len(paths) == 3
    assert recorder.recording_id != first_id
    assert recorder.error is None
    restored = [session for path in paths for session in read_recording(path)]
    assert {session.id for session in restored} == {session.id for session in sessions}


async def test_queue_overflow_seals_recorded_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder_module, "MAX_CHUNK", 1_500)
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    first = sample()
    recorder.enqueue(first)
    recorder.enqueue(sample())
    await recorder.stop()

    assert recorder.error is not None
    assert [session.id for session in read_recording(recorder.path(recording_id))] == [first.id]


async def test_pending_updates_keep_latest_complete_snapshot(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    session = sample()
    for index in range(100):
        session.error = f"update-{index}"
        recorder.enqueue(session)
    await recorder.stop()

    restored = list(read_recording(recorder.path(recording_id)))
    assert len(restored) == 1
    assert restored[0].error == "update-99"


async def test_burst_of_2000_requests_does_not_stop_recording(tmp_path):
    recorder = Recorder(tmp_path)
    recording_id = await recorder.start(None, [])
    sessions = [sample() for _ in range(2000)]
    for session in sessions:
        recorder.enqueue(session)
    assert recorder.active
    await recorder.stop()
    assert recorder.error is None
    assert {s.id for s in read_recording(recorder.path(recording_id))} == {s.id for s in sessions}


async def test_restart_after_overflow_without_manual_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder_module, "MAX_CHUNK", 1_500)
    recorder = Recorder(tmp_path)
    first_id = await recorder.start(None, [])
    recorder.enqueue(sample())
    recorder.enqueue(sample())
    assert not recorder.active
    second_id = await recorder.start(None, [])
    assert second_id != first_id
    assert recorder.active
    assert recorder.error is None
    recorder.enqueue(sample())
    await recorder.stop()
    assert len(list(read_recording(recorder.path(first_id)))) == 1
    assert len(list(read_recording(recorder.path(second_id)))) == 1


async def test_restart_after_disk_failure_without_manual_stop(tmp_path, monkeypatch):
    import asyncio
    recorder = Recorder(tmp_path)
    await recorder.start(None, [])
    def fail(data):
        raise OSError("disk full")
    monkeypatch.setattr(recorder._writer, "append", fail)
    recorder.enqueue(sample())
    await asyncio.wait_for(asyncio.shield(recorder._task), 5)
    assert recorder.error
    second_id = await recorder.start(None, [])
    recorder.enqueue(sample())
    await recorder.stop()
    assert recorder.error is None
    assert len(list(read_recording(recorder.path(second_id)))) == 1
