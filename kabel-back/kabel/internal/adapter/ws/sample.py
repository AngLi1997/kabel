from typing import Iterable

from fastapi import Depends, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from kabel.internal.clients.ws import sampleConnectionManager
from kabel.internal.common.websocket import ConnectionData, Message, MessageType
from kabel.internal.dependencies.user import verify_ws_token


class TaskSampleWsPayload(BaseModel):
    task_id: int
    user_id: int
    username: str
    sample_id: int


def get_task_sample_connection_payloads(conns: Iterable[ConnectionData]):
    if not conns:
        return Message(type=MessageType.PEERS, data=[])

    return Message(
        type=MessageType.PEERS,
        data=[
            TaskSampleWsPayload(
                task_id=conn.data.task_id,
                user_id=conn.data.user_id,
                username=conn.data.username,
                sample_id=conn.data.sample_id,
            )
            for conn in conns
        ],
    )


async def task_ws_endpoint(
    websocket: WebSocket,
    task_id: int,
    sample_id: int,
    user=Depends(verify_ws_token),
):
    if not user:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    client_id = f"task_{task_id}"

    async def sync_peers():
        connections = sampleConnectionManager.active_connections
        current_connections = connections.get(client_id, {})
        sample_payload = get_task_sample_connection_payloads(
            current_connections.values()
        )

        await sampleConnectionManager.send_message(
            client_id=client_id, message=sample_payload
        )

    connection = None

    async def cleanup():
        await sampleConnectionManager.disconnect(client_id, websocket)
        await sync_peers()

    try:
        connection = await sampleConnectionManager.connect(
            client_id,
            websocket,
            data=TaskSampleWsPayload(
                task_id=task_id,
                user_id=user.id,
                username=user.username,
                sample_id=sample_id,
            ),
        )

        await sync_peers()

        while True:
            try:
                data = await websocket.receive_text()
                message = Message.model_validate_json(data)

                if message.type == MessageType.PONG:
                    connection.update_heartbeat()
                elif message.type == MessageType.SAMPLE:
                    next_sample_id = (message.data or {}).get("sample_id")
                    if (
                        isinstance(next_sample_id, int)
                        and next_sample_id > 0
                        and next_sample_id != connection.data.sample_id
                    ):
                        connection.data.sample_id = next_sample_id
                        sampleConnectionManager.touch(client_id, connection.id)
                        await sync_peers()

            except WebSocketDisconnect as e:
                logger.info(
                    f"WebSocket disconnected for client {client_id}: Code={e.code}"
                )
                break

    except WebSocketDisconnect as e:
        logger.info(
            "WebSocket disconnected during connection setup for client "
            f"{client_id}: Code={e.code}"
        )
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
    finally:
        await cleanup()
