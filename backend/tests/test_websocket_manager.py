"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json

import pytest

from app.websocket_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_text(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_broadcast_sends_typed_timestamped_event():
    manager = ConnectionManager()
    websocket = FakeWebSocket()
    manager.active_connections.append(websocket)

    await manager.broadcast("record_ingested", {"payment_id": "pay_test_001"})

    assert len(websocket.messages) == 1
    message = json.loads(websocket.messages[0])
    assert message["type"] == "record_ingested"
    assert message["data"] == {"payment_id": "pay_test_001"}
    assert message["timestamp"]


@pytest.mark.asyncio
async def test_broadcast_removes_failed_connections():
    manager = ConnectionManager()

    class BrokenWebSocket:
        async def send_text(self, _message):
            raise RuntimeError("connection closed")

    broken = BrokenWebSocket()
    manager.active_connections.append(broken)

    await manager.broadcast("metric_update", {})

    assert manager.active_connections == []
