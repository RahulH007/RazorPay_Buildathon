"""
RecoverOS WebSocket Manager
Manages real-time WebSocket connections for the live dashboard.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json
from datetime import datetime, timezone
from typing import List

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events to all connected clients."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] WebSocket connected. Active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WS] WebSocket disconnected. Active: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: dict):
        """Broadcast a JSON event to all connected clients."""
        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        # Clean up broken connections
        for conn in disconnected:
            self.disconnect(conn)

    async def send_state_change(self, payment_id: str, from_state: str, to_state: str, details: dict = None):
        """Broadcast a state change event."""
        await self.broadcast("state_change", {
            "payment_id": payment_id,
            "from": from_state,
            "to": to_state,
            "details": details or {},
        })

    async def send_metric_update(self, metrics: dict):
        """Broadcast updated dashboard metrics."""
        await self.broadcast("metric_update", metrics)

    async def send_batch_progress(self, batch_id: str, processed: int, total: int, current_record: dict = None):
        """Broadcast batch processing progress."""
        await self.broadcast("batch_progress", {
            "batch_id": batch_id,
            "processed": processed,
            "total": total,
            "current_record": current_record,
        })


# Singleton instance
manager = ConnectionManager()
