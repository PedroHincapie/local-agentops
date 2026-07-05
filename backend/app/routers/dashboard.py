"""``GET /api/dashboard`` — vista consolidada que consume el frontend."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from app.db import get_session
from app.services.dashboard import build_dashboard
from app.services.websocket import manager

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(session: Session = Depends(get_session)) -> dict[str, Any]:
    return build_dashboard(session)


@router.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket, session: Session = Depends(get_session)) -> None:
    await manager.connect(websocket)
    try:
        # Send initial dashboard state immediately upon connection
        initial_data = build_dashboard(session)
        await websocket.send_json(initial_data)
        # Keep connection open to listen for client disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

