from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    events = websocket.app.state.events
    try:
        async for event in events.subscribe():
            await websocket.send_json(event)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return

