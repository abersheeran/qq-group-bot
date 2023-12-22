import asyncio
from contextlib import asynccontextmanager
import contextvars
import json
from typing import Any, AsyncGenerator, TypedDict, Required

import httpx
from loguru import logger
import websockets

BotClient: contextvars.ContextVar[httpx.AsyncClient] = contextvars.ContextVar(
    "BotClient"
)


@asynccontextmanager
async def initial_openapi_client(bot_url: str, authorization: str):
    """
    https://bot.q.qq.com/wiki/develop/api/#%E7%A5%A8%E6%8D%AE
    """
    async with httpx.AsyncClient(
        base_url=bot_url, headers={"Authorization": authorization}
    ) as client:
        token = BotClient.set(client)
        try:
            yield client
        finally:
            BotClient.reset(token)


async def get_gateway_url(bot_url: str, authorization: str) -> str:
    async with initial_openapi_client(bot_url, authorization) as client:
        resp = await client.get("/gateway")
        return resp.json()["url"]


class Event(TypedDict, total=False):
    op: Required[int]
    s: int
    t: str
    d: dict[str, Any]


async def wss_connect(
    wss_url: str,
    authorization: str,
    intents: int,
    shard: tuple[int, int],
    resume: tuple[str, int] | None = None,
) -> AsyncGenerator[tuple[str, int] | Event, None]:
    queue = asyncio.Queue(1)
    seq: int | None

    async with websockets.connect(wss_url) as websocket:
        data = await websocket.recv()
        event = json.loads(data)
        heartbeat_interval = event["d"]["heartbeat_interval"]
        if resume is None:
            logger.info("Identify")
            data = json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": authorization,
                        "intents": intents,
                        "shard": shard,
                        "properties": None,
                    },
                }
            )
            await websocket.send(data)
            data = await websocket.recv()
            event = json.loads(data)
            if event.get("t") != "READY":
                logger.warning(f"Unexpected event: {event}")
                return
            seq = None
            session_id = event["d"]["session_id"]
        else:
            logger.info(f"Resume: {resume}")
            session_id, seq = resume
            data = json.dumps(
                {
                    "op": 6,
                    "d": {
                        "token": authorization,
                        "session_id": session_id,
                        "seq": seq,
                    },
                }
            )
            await websocket.send(data)

        stop = False

        async def heartbeat():
            while True:
                await websocket.send(json.dumps({"op": 1, "d": seq}))
                await asyncio.sleep(heartbeat_interval / 1000)

        async def fetch_event():
            nonlocal seq, stop

            while True:
                data = await websocket.recv()
                assert isinstance(data, str)
                event: Event = json.loads(data)
                if (s := event.get("s")) is not None:
                    seq = s
                op = event["op"]
                if op == 0 and event.get("t") == "RESUMED":
                    continue
                if op == 11:  # Heartbeat ACK
                    continue
                if op == 7:  # Reconnect
                    stop = True
                    logger.info(f"Reconnect: {event}")
                    return
                await queue.put(event)

        heartbeat_task = asyncio.create_task(heartbeat())
        fetch_event_task = asyncio.create_task(fetch_event())

        try:
            while not stop:
                try:
                    yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.1)
        finally:
            done, pending = await asyncio.wait(
                [heartbeat_task, fetch_event_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            [task.cancel() for task in pending]
            [task.result() for task in done]
            if seq is not None:
                yield session_id, seq


async def fetch_events(
    wss_url: str,
    authorization: str,
    intents: int,
    shard: tuple[int, int] = (0, 1),
) -> AsyncGenerator[Event, None]:
    events = wss_connect(wss_url, authorization, intents, shard)
    while True:
        async for event in events:
            match event:
                case (session_id, seq):
                    events = wss_connect(
                        wss_url, authorization, intents, shard, (session_id, seq)
                    )
                case _:
                    yield event
