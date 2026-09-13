import pytest

from backend.store.buffer import SessionBuffer
from backend.store.model import ApplicationInfo, Connection, Header, Payload, Request, Response, Session


@pytest.mark.asyncio
async def test_ring_buffer_evicts_oldest_session() -> None:
    buffer = SessionBuffer(max_sessions=2, max_bytes=1_000_000)
    sessions = [Session(connection_id=str(i), type="tcp", connection=Connection()) for i in range(3)]
    for session in sessions:
        await buffer.upsert(session)
    assert len(buffer) == 2
    assert await buffer.get(sessions[0].id) is None
    assert await buffer.get(sessions[2].id) is not None


@pytest.mark.asyncio
async def test_clear_resets_memory_usage() -> None:
    buffer = SessionBuffer(max_sessions=10, max_bytes=1_000_000)
    await buffer.upsert(Session(connection_id="1", type="tcp", connection=Connection()))
    await buffer.clear()
    assert len(buffer) == 0
    assert buffer.memory_bytes == 0


@pytest.mark.asyncio
async def test_binary_payload_is_preserved_and_json_serializable() -> None:
    raw = b"\x00\xff\x10unknown"
    session = Session(
        connection_id="binary",
        type="http",
        connection=Connection(),
        request=Request(
            method="POST",
            scheme="https",
            host="example.invalid",
            port=443,
            path="/",
            body=Payload(raw=raw, size_bytes=len(raw), is_binary=True),
        ),
    )
    buffer = SessionBuffer(max_sessions=10, max_bytes=1_000_000)
    await buffer.upsert(session)
    serialized = session.model_dump_json()
    assert "AP8QdW5rbm93bg==" in serialized
    assert (await buffer.get(session.id)).request.body.raw == raw


@pytest.mark.asyncio
async def test_search_matches_nested_payload_headers_and_raw_text() -> None:
    session = Session(
        connection_id="searchable",
        type="http",
        application=ApplicationInfo(name="sample.exe"),
        connection=Connection(),
        request=Request(
            method="POST",
            scheme="https",
            host="example.invalid",
            port=443,
            path="/messages",
            headers=[Header(name="x-trace", value="trace-value")],
            body=Payload(
                raw=b'{"message":{"content":"selam"}}',
                parsed={"message": {"content": "selam"}},
                size_bytes=31,
            ),
        ),
        response=Response(status_code=200),
    )
    buffer = SessionBuffer(max_sessions=10, max_bytes=1_000_000)
    await buffer.upsert(session)

    assert [item.id for item in await buffer.list(query="selam")] == [session.id]
    assert [item.id for item in await buffer.list(query="message.content")] == [session.id]
    assert [item.id for item in await buffer.list(query="trace-value")] == [session.id]
    assert await buffer.list(query="bulunmayan") == []


@pytest.mark.asyncio
async def test_search_document_is_replaced_when_session_is_updated() -> None:
    session = Session(
        connection_id="updated",
        type="http",
        connection=Connection(),
        request=Request(method="GET", scheme="https", host="example.invalid", port=443, path="/old"),
    )
    buffer = SessionBuffer(max_sessions=10, max_bytes=1_000_000)
    await buffer.upsert(session)
    session.request.path = "/new"
    await buffer.upsert(session)

    assert await buffer.list(query="/old") == []
    assert [item.id for item in await buffer.list(query="/new")] == [session.id]
