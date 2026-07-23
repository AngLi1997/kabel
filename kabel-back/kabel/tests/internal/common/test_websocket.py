import asyncio
import json
from types import SimpleNamespace

from kabel.internal.common.websocket import ConnectionManager, Message, MessageType


class FakeWebSocket:
    def __init__(self, tracker=None, fail=False):
        self.accepted = False
        self.messages = []
        self.tracker = tracker
        self.fail = fail

    async def accept(self):
        self.accepted = True

    async def send_text(self, payload):
        if self.fail:
            raise RuntimeError("connection closed")

        if self.tracker:
            self.tracker["active"] += 1
            self.tracker["max_active"] = max(
                self.tracker["max_active"], self.tracker["active"]
            )
            await asyncio.sleep(0)
            self.tracker["active"] -= 1

        self.messages.append(json.loads(payload))


def test_broadcasts_to_twenty_connections_concurrently():
    async def run():
        manager = ConnectionManager()
        tracker = {"active": 0, "max_active": 0}
        sockets = []

        for sample_id in range(1, 21):
            websocket = FakeWebSocket(tracker)
            sockets.append(websocket)
            await manager.connect(
                "task_1",
                websocket,
                data=SimpleNamespace(sample_id=sample_id, username=str(sample_id)),
            )

        await manager.send_message(
            "task_1", message=Message(type=MessageType.PEERS, data=[])
        )

        assert tracker["max_active"] == 20
        assert all(
            websocket.messages == [{"type": "peers", "data": []}]
            for websocket in sockets
        )

        for websocket in sockets:
            await manager.disconnect("task_1", websocket)

    asyncio.run(run())


def test_broadcast_can_be_scoped_to_current_sample():
    async def run():
        manager = ConnectionManager()
        sockets = []

        for sample_id in (1, 1, 2):
            websocket = FakeWebSocket()
            sockets.append(websocket)
            await manager.connect(
                "task_1",
                websocket,
                data=SimpleNamespace(sample_id=sample_id, username=str(sample_id)),
            )

        await manager.send_message(
            "task_1",
            message=Message(type=MessageType.UPDATE, data={"sample_id": 1}),
            predicate=lambda connection: connection.data.sample_id == 1,
        )

        assert len(sockets[0].messages) == 1
        assert len(sockets[1].messages) == 1
        assert sockets[2].messages == []

        for websocket in sockets:
            await manager.disconnect("task_1", websocket)

    asyncio.run(run())


def test_failed_connection_does_not_block_other_users():
    async def run():
        manager = ConnectionManager()
        failed = FakeWebSocket(fail=True)
        healthy = FakeWebSocket()
        await manager.connect(
            "task_1",
            failed,
            data=SimpleNamespace(sample_id=1, username="failed"),
        )
        await manager.connect(
            "task_1",
            healthy,
            data=SimpleNamespace(sample_id=1, username="healthy"),
        )

        await manager.send_message("task_1", message=Message(type=MessageType.PING))

        assert healthy.messages == [{"type": "ping", "data": None}]
        assert len(manager.active_connections["task_1"]) == 1
        await manager.disconnect("task_1", healthy)

    asyncio.run(run())
