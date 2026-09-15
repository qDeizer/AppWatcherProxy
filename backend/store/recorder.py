from __future__ import annotations

import asyncio
import os
import struct
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from backend.diagnostics import report_exception
from backend.store.model import Session
from backend.store.windows_protection import protect_key, unprotect_key

MAGIC = b"AWP1"
LOCAL_MAGIC = b"AWP2"
MAX_CHUNK = 96 * 1024 * 1024
MAX_FILE = 1024 * 1024 * 1024
END_MARKER = b'"end"'
PLAIN_END_MARKER = b'{"end":true}'
PLAIN_SYNC_BYTES = 8 * 1024 * 1024


def derive_key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


class RecordingWriter:
    def __init__(self, path: Path, password: str | None) -> None:
        salt = os.urandom(16)
        if password is None:
            secret = os.urandom(32)
            wrapped = protect_key(secret)
            if len(wrapped) > 4096:
                raise ValueError("Windows anahtar boyutu geçersiz")
            self.header = LOCAL_MAGIC + salt + struct.pack(">H", len(wrapped)) + wrapped
            key = secret
        else:
            self.header = MAGIC + salt
            key = derive_key(password, salt)
        self.cipher = AESGCM(key)
        self.sequence = 0
        self.file = path.open("xb")
        self.file.write(self.header)

    def append(self, data: bytes) -> None:
        if len(data) > MAX_CHUNK - 28:
            raise ValueError("Tek kayıt parçası boyut sınırını aşıyor")
        nonce = os.urandom(12)
        aad = self.header + struct.pack(">Q", self.sequence)
        encrypted = nonce + self.cipher.encrypt(nonce, data, aad)
        if self.file.tell() + len(encrypted) + 4 > MAX_FILE:
            raise ValueError("Kayıt 1 GB sınırına ulaştı; yeni kayıt başlatın")
        self.file.write(struct.pack(">I", len(encrypted)) + encrypted)
        self.file.flush()
        os.fsync(self.file.fileno())
        self.sequence += 1

    def close(self) -> None:
        self.file.close()


class PlainRecordingWriter:
    """Append complete session snapshots as readable JSON Lines."""

    def __init__(self, path: Path) -> None:
        self.file = path.open("xb")
        self._pending_sync_bytes = 0

    def append(self, data: bytes) -> None:
        if len(data) > MAX_CHUNK - 1:
            raise ValueError("Tek kayıt parçası boyut sınırını aşıyor")
        if self.file.tell() + len(data) + 1 > MAX_FILE:
            raise ValueError("Kayıt 1 GB sınırına ulaştı; yeni kayıt başlatın")
        self.file.write(data + b"\n")
        self._pending_sync_bytes += len(data) + 1
        if self._pending_sync_bytes >= PLAIN_SYNC_BYTES or data == PLAIN_END_MARKER:
            self.file.flush()
            os.fsync(self.file.fileno())
            self._pending_sync_bytes = 0

    def can_append_with_end(self, data: bytes) -> bool:
        return self.file.tell() + len(data) + 1 + len(PLAIN_END_MARKER) + 1 <= MAX_FILE

    def close(self) -> None:
        if not self.file.closed:
            try:
                self.file.flush()
                os.fsync(self.file.fileno())
            finally:
                self.file.close()


def _read_plain_recording(path: Path):
    with path.open("rb") as source:
        if path.stat().st_size > MAX_FILE:
            raise ValueError("Kayıt boyut sınırını aşıyor")
        while True:
            raw = source.readline(MAX_CHUNK + 1)
            if not raw or not raw.endswith(b"\n"):
                raise ValueError("Kayıt tamamlanmamış veya kesilmiş; orijinal dosya korundu")
            if len(raw) > MAX_CHUNK:
                raise ValueError("Kayıt parçası boyut sınırını aşıyor")
            if raw[:-1] == PLAIN_END_MARKER:
                if source.read(1):
                    raise ValueError("Kayıt sonrasında beklenmeyen veri")
                return
            yield Session.model_validate_json(raw)


def read_recording(path: Path, password: str | None = None):
    if path.suffix == ".jsonl":
        yield from _read_plain_recording(path)
        return
    with path.open("rb") as source:
        if path.stat().st_size > MAX_FILE:
            raise ValueError("Kayıt boyut sınırını aşıyor")
        prefix = source.read(20)
        if len(prefix) != 20:
            raise ValueError("Geçersiz kayıt biçimi")
        if prefix[:4] == LOCAL_MAGIC:
            size_data = source.read(2)
            if len(size_data) != 2:
                raise ValueError("Kayıt anahtarı kesilmiş")
            wrapped_size = struct.unpack(">H", size_data)[0]
            if not 1 <= wrapped_size <= 4096:
                raise ValueError("Geçersiz kayıt anahtarı")
            wrapped = source.read(wrapped_size)
            if len(wrapped) != wrapped_size:
                raise ValueError("Kayıt anahtarı kesilmiş")
            header = prefix + size_data + wrapped
            key = unprotect_key(wrapped)
            if len(key) != 32:
                raise ValueError("Geçersiz Windows kayıt anahtarı")
        elif prefix[:4] == MAGIC:
            if not password:
                raise ValueError("Eski kayıt için parola gerekli")
            header = prefix
            key = derive_key(password, prefix[4:])
        else:
            raise ValueError("Geçersiz kayıt biçimi")
        cipher = AESGCM(key)
        sequence = 0
        while True:
            length = source.read(4)
            if len(length) != 4:
                raise ValueError("Kayıt tamamlanmamış veya kesilmiş; orijinal dosya korundu")
            size = struct.unpack(">I", length)[0]
            if not 28 <= size <= MAX_CHUNK:
                raise ValueError("Geçersiz kayıt parçası")
            encrypted = source.read(size)
            if len(encrypted) != size:
                raise ValueError("Kayıt parçası kesilmiş")
            try:
                raw = cipher.decrypt(
                    encrypted[:12], encrypted[12:], header + struct.pack(">Q", sequence)
                )
            except InvalidTag as exc:
                raise ValueError("Parola yanlış veya kayıt değiştirilmiş") from exc
            sequence += 1
            if raw == b'"end"':
                if source.read(1):
                    raise ValueError("Kayıt sonrasında beklenmeyen veri")
                return
            yield Session.model_validate_json(raw)


def convert_to_plain(path: Path, root: Path, password: str | None = None) -> tuple[list[str], bool]:
    """Copy authenticated legacy sessions as JSONL, retaining the original."""
    if path.suffix != ".awp":
        raise ValueError("Yalnızca eski şifreli kayıtlar dönüştürülebilir")
    incomplete = False

    def readable_sessions():
        nonlocal incomplete
        try:
            yield from read_recording(path, password)
        except ValueError as exc:
            if str(exc) not in {
                "Kayıt tamamlanmamış veya kesilmiş; orijinal dosya korundu",
                "Kayıt parçası kesilmiş",
            }:
                raise
            incomplete = True

    # Authenticate the whole readable prefix before creating plaintext output.
    count = sum(1 for _ in readable_sessions())
    if not count:
        raise ValueError("Kurtarılabilir oturum bulunamadı")
    root.mkdir(parents=True, exist_ok=True)
    ids: list[str] = []
    writer: PlainRecordingWriter | None = None
    try:
        for session in readable_sessions():
            data = session.model_dump_json().encode("utf-8")
            if writer is None or not writer.can_append_with_end(data):
                if writer is not None:
                    writer.append(PLAIN_END_MARKER)
                    writer.close()
                recording_id = uuid4().hex
                writer = PlainRecordingWriter(root / f"{recording_id}.jsonl")
                ids.append(recording_id)
                if not writer.can_append_with_end(data):
                    raise ValueError("Tek oturum kayıt parçası sınırını aşıyor")
            writer.append(data)
        if writer is None:
            recording_id = uuid4().hex
            writer = PlainRecordingWriter(root / f"{recording_id}.jsonl")
            ids.append(recording_id)
        writer.append(PLAIN_END_MARKER)
    finally:
        if writer is not None:
            writer.close()
    return ids, incomplete


class Recorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.active = False
        self.error: str | None = None
        self.recording_id: str | None = None
        self.applications: set[str] = set()
        self.started_at: datetime | None = None
        self._writer: PlainRecordingWriter | None = None
        # Bound payload bytes, not the number of small concurrent requests.
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._queued_snapshots: dict[str, bytes] = {}
        self._queued_bytes = 0
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self, password: str | None, applications: list[str]) -> str:
        async with self._lock:
            if self.active:
                raise ValueError("Önce mevcut kaydı durdurun")
            if self._task is not None:
                await asyncio.shield(self._task)
                self._task = None
                self._writer = None
            if password is not None:
                raise ValueError("Parolalı yeni kayıt desteklenmiyor")
            self.root.mkdir(parents=True, exist_ok=True)
            recording_id = uuid4().hex
            self._writer = await asyncio.to_thread(
                PlainRecordingWriter, self.root / f"{recording_id}.jsonl"
            )
            self.recording_id = recording_id
            self.applications = set(applications)
            self.started_at = datetime.now(UTC)
            self.error = None
            self.active = True
            self._task = asyncio.create_task(self._run())
            return recording_id

    def enqueue(self, session: Session) -> None:
        # enqueue is called for live updates, not a replay of the RAM buffer.
        # A WebSocket opened before recording may carry new messages now.
        if not self.active:
            return
        if self.applications and session.application.name not in self.applications:
            return
        data = session.model_dump_json().encode("utf-8")
        previous = self._queued_snapshots.get(session.id)
        next_bytes = self._queued_bytes - (len(previous) if previous else 0) + len(data)
        if next_bytes > MAX_CHUNK:
            self.error = "Disk kaydı yetişemedi; kayıt durduruldu. Önceki oturumlar korundu."
            self.active = False
            if not self._queue.full():
                self._queue.put_nowait(None)
            return
        self._queued_snapshots[session.id] = data
        self._queued_bytes = next_bytes
        if previous is None:
            self._queue.put_nowait(session.id)

    async def _run(self) -> None:
        try:
            while True:
                session_id = await self._queue.get()
                if session_id is None:
                    await asyncio.to_thread(self._writer.append, PLAIN_END_MARKER)
                    break
                batch = [self._queued_snapshots.pop(session_id)]
                batch_bytes = len(batch[0])
                finish = False
                while not self._queue.empty() and batch_bytes < PLAIN_SYNC_BYTES:
                    session_id = self._queue.get_nowait()
                    if session_id is None:
                        finish = True
                        break
                    data = self._queued_snapshots.pop(session_id)
                    batch.append(data)
                    batch_bytes += len(data)
                self._queued_bytes -= batch_bytes
                await asyncio.to_thread(self._write_batch, batch)
                if finish:
                    await asyncio.to_thread(self._writer.append, PLAIN_END_MARKER)
                    break
                if not self.active and self.error and self._queue.empty():
                    await asyncio.to_thread(self._writer.append, PLAIN_END_MARKER)
                    break
        except (OSError, ValueError) as exc:
            report_exception("recording_write_failed", exc)
            self.error = f"Disk kaydı başarısız ({type(exc).__name__}); boş alanı ve izinleri kontrol edin."
            self.active = False
        finally:
            try:
                await asyncio.to_thread(self._writer.close)
            except OSError as exc:
                report_exception("recording_close_failed", exc)
                self.error = "Kayıt dosyası kapatılamadı; disk durumunu kontrol edin."
                self.active = False
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queued_snapshots.clear()
            self._queued_bytes = 0

    def _write_batch(self, batch: list[bytes]) -> None:
        # One thread handoff per batch, instead of one for every HTTP/SSE update.
        for data in batch:
            if not self._writer.can_append_with_end(data):
                self._writer.append(PLAIN_END_MARKER)
                self._writer.close()
                next_id = uuid4().hex
                self._writer = PlainRecordingWriter(self.root / f"{next_id}.jsonl")
                self.recording_id = next_id
                if not self._writer.can_append_with_end(data):
                    raise ValueError("Tek oturum kayıt parçası sınırını aşıyor")
            self._writer.append(data)

    async def stop(self) -> None:
        async with self._lock:
            self.active = False
            if self._task is not None:
                if not self._task.done():
                    await self._queue.put(None)
                await asyncio.shield(self._task)
            self._task = None
            self._writer = None
            self._queue = asyncio.Queue()
            self._queued_snapshots = {}
            self._queued_bytes = 0

    def path(self, recording_id: str) -> Path:
        if len(recording_id) != 32 or any(char not in "0123456789abcdef" for char in recording_id):
            raise ValueError("Geçersiz kayıt kimliği")
        path = self.root / f"{recording_id}.jsonl"
        if not path.is_file():
            path = self.root / f"{recording_id}.awp"
        if path.is_symlink() or not path.is_file():
            raise ValueError("Kayıt bulunamadı")
        if recording_id == self.recording_id and self._task is not None and not self._task.done():
            raise ValueError("Önce kaydı durdurun")
        return path

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        def requires_password(path: Path) -> bool:
            with path.open("rb") as source:
                return source.read(4) == MAGIC
        paths = list(self.root.glob("*.jsonl")) + list(self.root.glob("*.awp"))
        items = []
        for path in paths:
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stat = path.stat()
                password_required = requires_password(path) if path.suffix == ".awp" else False
            except OSError:
                # A removed/locked file must not hide all other recordings.
                continue
            items.append({"id": path.stem, "size": stat.st_size,
             "format": "jsonl" if path.suffix == ".jsonl" else "awp",
             "encrypted": path.suffix == ".awp",
             "password_required": password_required,
             "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()})
        return sorted(items, key=lambda item: item["modified"], reverse=True)
