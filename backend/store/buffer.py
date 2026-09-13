from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterator

from backend.store.model import Session
from backend.store.search import build_search_document, matches_search


class SessionBuffer:
    """A count- and byte-bounded RAM-only session buffer."""

    def __init__(self, max_sessions: int, max_bytes: int) -> None:
        if max_sessions <= 0 or max_bytes <= 0:
            raise ValueError("Buffer limits must be positive")
        self.max_sessions = max_sessions
        self.max_bytes = max_bytes
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._sizes: dict[str, int] = {}
        self._search_documents: dict[str, str] = {}
        self._bytes = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _measure(session: Session) -> int:
        return len(session.model_dump_json().encode("utf-8")) * 2

    async def upsert(self, session: Session) -> list[str]:
        evicted: list[str] = []
        search_document = build_search_document(session)
        size = self._measure(session) + len(search_document.encode("utf-8"))
        async with self._lock:
            previous = self._sizes.pop(session.id, 0)
            self._bytes -= previous
            self._sessions.pop(session.id, None)
            self._sessions[session.id] = session
            self._sizes[session.id] = size
            self._search_documents[session.id] = search_document
            self._bytes += size
            while (
                len(self._sessions) > self.max_sessions or self._bytes > self.max_bytes
            ):
                session_id, _ = self._sessions.popitem(last=False)
                self._bytes -= self._sizes.pop(session_id)
                self._search_documents.pop(session_id, None)
                evicted.append(session_id)
        return evicted

    async def get(self, session_id: str) -> Session | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def list(
        self, *, limit: int = 200, offset: int = 0, query: str = ""
    ) -> list[Session]:
        async with self._lock:
            values = list(reversed(self._sessions.values()))
            if query:
                values = [
                    session
                    for session in values
                    if matches_search(self._search_documents.get(session.id, ""), query)
                ]
            return values[offset : offset + limit]

    async def count(self, query: str = "") -> int:
        async with self._lock:
            if not query:
                return len(self._sessions)
            return sum(matches_search(document, query) for document in self._search_documents.values())

    async def clear(self) -> None:
        async with self._lock:
            self._sessions.clear()
            self._sizes.clear()
            self._search_documents.clear()
            self._bytes = 0

    async def applications(self) -> list[dict]:
        async with self._lock:
            grouped: dict[tuple[str, str | None], dict] = {}
            for session in self._sessions.values():
                key = (session.application.name, session.application.executable_path)
                app = grouped.setdefault(
                    key,
                    {
                        "name": session.application.name,
                        "executable_path": session.application.executable_path,
                        "session_count": 0,
                        "processes": {},
                    },
                )
                app["session_count"] += 1
                if session.process.pid is not None:
                    app["processes"][session.process.pid] = {
                        "pid": session.process.pid,
                        "name": session.process.name,
                    }
            result = []
            for app in grouped.values():
                app["processes"] = list(app["processes"].values())
                app["process_count"] = len(app["processes"])
                result.append(app)
            return sorted(result, key=lambda item: (-item["session_count"], item["name"]))

    @property
    def memory_bytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._sessions)

    def __iter__(self) -> Iterator[Session]:
        return iter(self._sessions.values())
