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

MAGIC = b"AWP1"
MAX_CHUNK = 96 * 1024 * 1024
MAX_FILE = 1024 * 1024 * 1024


def derive_key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


class RecordingWriter:
    def __init__(self, path: Path, password: str) -> None:
        self.header = MAGIC + os.urandom(16)
        self.cipher = AESGCM(derive_key(password, self.header[4:]))
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


def read_recording(path: Path, password: str):
    with path.open("rb") as source:
        if path.stat().st_size > MAX_FILE:
            raise ValueError("Kayıt boyut sınırını aşıyor")
        header = source.read(20)
        if len(header) != 20 or header[:4] != MAGIC:
            raise ValueError("Geçersiz kayıt biçimi")
        cipher = AESGCM(derive_key(password, header[4:]))
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


class Recorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.active = False
        self.error: str | None = None
        self.recording_id: str | None = None
        self.applications: set[str] = set()
        self.started_at: datetime | None = None
        self._writer: RecordingWriter | None = None
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
        self._queued_bytes = 0
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self, password: str, applications: list[str]) -> str:
        async with self._lock:
            if self.active or self._task is not None:
                raise ValueError("Önce mevcut kaydı durdurun")
            if len(password) < 8:
                raise ValueError("Parola en az 8 karakter olmalı")
            self.root.mkdir(parents=True, exist_ok=True)
            recording_id = uuid4().hex
            self._writer = await asyncio.to_thread(
                RecordingWriter, self.root / f"{recording_id}.awp", password
            )
            self.recording_id = recording_id
            self.applications = set(applications)
            self.started_at = datetime.now(UTC)
            self.error = None
            self.active = True
            self._task = asyncio.create_task(self._run())
            return recording_id

    def enqueue(self, session: Session) -> None:
        if not self.active or session.opened_at < self.started_at:
            return
        if self.applications and session.application.name not in self.applications:
            return
        data = session.model_dump_json().encode("utf-8")
        if self._queue.full() or self._queued_bytes + len(data) > MAX_CHUNK:
            self.error = "Disk kaydı yetişemedi; kayıt durduruldu. Dosya eksik olabilir."
            self.active = False
            return
        self._queued_bytes += len(data)
        self._queue.put_nowait(data)

    async def _run(self) -> None:
        try:
            while True:
                data = await self._queue.get()
                if data is None:
                    if not self.error:
                        await asyncio.to_thread(self._writer.append, b'"end"')
                    break
                self._queued_bytes -= len(data)
                await asyncio.to_thread(self._writer.append, data)
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
            self._queued_bytes = 0

    async def stop(self) -> None:
        async with self._lock:
            self.active = False
            if self._task is not None:
                if not self._task.done():
                    await self._queue.put(None)
                await self._task
            self._task = None
            self._writer = None
            self._queue = asyncio.Queue(maxsize=64)
            self._queued_bytes = 0

    def path(self, recording_id: str) -> Path:
        if len(recording_id) != 32 or any(char not in "0123456789abcdef" for char in recording_id):
            raise ValueError("Geçersiz kayıt kimliği")
        path = self.root / f"{recording_id}.awp"
        if path.is_symlink() or not path.is_file():
            raise ValueError("Kayıt bulunamadı")
        if recording_id == self.recording_id and self._task is not None:
            raise ValueError("Önce kaydı durdurun")
        return path

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        return [
            {"id": path.stem, "size": path.stat().st_size,
             "modified": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()}
            for path in sorted(self.root.glob("*.awp"), key=lambda item: item.stat().st_mtime, reverse=True)
            if not path.is_symlink()
        ]
