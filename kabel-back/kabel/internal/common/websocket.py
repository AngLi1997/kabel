import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict

from fastapi import WebSocket
from loguru import logger
from pydantic import BaseModel

HEARTBEAT_INTERVAL = 30
HEARTBEAT_TIMEOUT = 60
SEND_TIMEOUT = 5


class MessageType(str, Enum):
    PEERS = "peers"
    PING = "ping"
    PONG = "pong"
    UPDATE = "update"
    SAMPLE = "sample"


class Message(BaseModel):
    type: MessageType
    data: Any = None


@dataclass
class ConnectionData:
    id: str = None
    ws: WebSocket = None
    data: Any = None
    heartbeat_task: asyncio.Task = None
    last_heartbeat: float = field(default_factory=time.time)

    def update_heartbeat(self):
        self.last_heartbeat = time.time()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, ConnectionData]] = {}

    def _get_connection(
        self, client_id: str, connection_id: uuid.UUID | str
    ) -> ConnectionData | None:
        if client_id in self.active_connections:
            return self.active_connections[client_id].get(connection_id)

        return None

    async def _heartbeat(self, client_id: str, connection_id: str):
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                connection = self._get_connection(client_id, connection_id)
                if not connection:
                    break

                await self.send_message(
                    client_id, connection_id, Message(type=MessageType.PING)
                )

                if time.time() - connection.last_heartbeat > HEARTBEAT_TIMEOUT:
                    logger.error(
                        f"Heartbeat timeout for client {connection.data.username}"
                    )
                    await self.disconnect(client_id, connection.ws)
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat for client {client_id}: {e}")
                break

    async def connect(
        self, client_id: str, websocket: WebSocket, data: Any = None
    ) -> ConnectionData:
        await websocket.accept()

        logger.info(f"Client {client_id} connected")
        connection_id = str(uuid.uuid4())
        connection_data = ConnectionData(
            id=connection_id,
            ws=websocket,
            data=data,
            last_heartbeat=time.time(),
            heartbeat_task=asyncio.create_task(
                self._heartbeat(client_id, connection_id)
            ),
        )

        self.active_connections.setdefault(client_id, {})[
            connection_id
        ] = connection_data

        return connection_data

    def touch(self, client_id: str, connection_id: str):
        """Move a connection to the end, preserving sample arrival order."""
        connections = self.active_connections.get(client_id)
        if not connections or connection_id not in connections:
            return

        connection = connections.pop(connection_id)
        connections[connection_id] = connection

    async def disconnect(self, client_id: str, websocket: WebSocket):
        if client_id not in self.active_connections:
            return

        connection_to_remove = None
        for connection in self.active_connections[client_id].values():
            if connection.ws == websocket:
                if connection.heartbeat_task:
                    connection.heartbeat_task.cancel()
                connection_to_remove = connection
                logger.info(f"Client {client_id} disconnected")
                break

        if connection_to_remove is not None:
            del self.active_connections[client_id][connection_to_remove.id]

        if (
            client_id in self.active_connections
            and not self.active_connections[client_id]
        ):
            del self.active_connections[client_id]

    async def _send_message(
        self, client_id: str, connection: ConnectionData, payload: str
    ):
        try:
            await asyncio.wait_for(
                connection.ws.send_text(payload), timeout=SEND_TIMEOUT
            )
        except Exception as exc:
            logger.warning(
                "Failed to send WebSocket message to client {}: {}", client_id, exc
            )
            await self.disconnect(client_id, connection.ws)

    async def send_message(
        self,
        client_id: str,
        conn_id: uuid.UUID | str | None = None,
        message: Message = None,
        predicate: Callable[[ConnectionData], bool] | None = None,
    ):
        if message is None:
            return

        if conn_id:
            connection = self._get_connection(client_id, conn_id)
            if connection:
                await self._send_message(
                    client_id, connection, message.model_dump_json()
                )
            return

        connections = list(self.active_connections.get(client_id, {}).values())
        if predicate:
            connections = [
                connection for connection in connections if predicate(connection)
            ]

        if not connections:
            return

        payload = message.model_dump_json()
        await asyncio.gather(
            *(
                self._send_message(client_id, connection, payload)
                for connection in connections
            )
        )
