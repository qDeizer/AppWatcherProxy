from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psutil

from backend.store.model import ApplicationInfo, ProcessInfo


def resolve_process(pid: int | None) -> tuple[ApplicationInfo, ProcessInfo]:
    if not pid:
        return ApplicationInfo(), ProcessInfo()
    try:
        process = psutil.Process(pid)
        path = process.exe() or None
        name = process.name() or (path.rsplit("\\", 1)[-1] if path else "Unknown")
        started = datetime.fromtimestamp(process.create_time(), UTC)
        return (
            ApplicationInfo(name=name, executable_path=path),
            ProcessInfo(pid=pid, name=name, executable_path=path, start_time=started),
        )
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return ApplicationInfo(), ProcessInfo(pid=pid)


def _socket_tuple(value: Any) -> tuple[str, int] | None:
    if not value or not isinstance(value, tuple) or len(value) < 2:
        return None
    return str(value[0]), int(value[1])


def find_connection_pid(client_address: Any, server_address: Any) -> int | None:
    """Best-effort PID lookup from a captured socket pair.

    Local mode preserves the originating endpoint, so on Windows the tuple can
    be matched against the OS TCP table without injecting into target processes.
    """

    client = _socket_tuple(client_address)
    server = _socket_tuple(server_address)
    if client is None:
        return None
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        return None
    for connection in connections:
        local = _socket_tuple(connection.laddr)
        remote = _socket_tuple(connection.raddr)
        if local == client and (server is None or remote == server):
            return connection.pid
        if remote == client and (server is None or local == server):
            return connection.pid
    return None
