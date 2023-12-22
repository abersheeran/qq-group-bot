import asyncio
import base64
import datetime
import os
from typing import Any
import httpx

from loguru import logger
from motor.motor_asyncio import AsyncIOMotorClient

from qqgroupbot.core import Event, initial_openapi_client, fetch_events, get_gateway_url
from qqgroupbot.apis.reply_group_message import reply_group_message
from qqgroupbot.aichat.gemini import (
    generate_content,
    GenerateSafeError,
    GenerateResponseError,
    GenerateNetworkError,
    Content as GeminiRequestContent,
    Part as GeminiRequestPart,
    initial_gemini_client,
    is_supported_mime_type,
)
from qqgroupbot.command import command, CommandMatcher

BOT_ID = os.environ["BOT_ID"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

BOT_URL = os.environ.get("BOT_URL", "https://api.sgroup.qq.com")
AUTHORIZATION = f"Bot {BOT_ID}.{BOT_TOKEN}"

GEMINI_PRO_KEY = os.environ["GEMINI_PRO_KEY"]
GEMINI_PRO_URL = os.environ.get("GEMINI_PRO_URL")
GEMINI_PRO_VISION_URL = os.environ.get("GEMINI_PRO_VISION_URL")


async def download_image(url: str) -> str:
    async with httpx.AsyncClient() as client:
        return base64.b64encode(await (await client.get(url)).aread()).decode()


client = AsyncIOMotorClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
db = client["paimeng"]
collection_messages = db["messages"]
collection_multi_turn_conversations = db["turns_messages"]


class Commands(CommandMatcher):
    @command("echo")
    async def echo(
        self,
        content: str,
        /,
        *,
        group_openid: str,
        message_id: str,
        **_: Any,
    ) -> None:
        await reply_group_message(
            group_openid=group_openid,
            message_id=message_id,
            content=content,
        )

    @command("status")
    async def status(
        self,
        content: str,
        /,
        *,
        group_openid: str,
        message_id: str,
        **_: Any,
    ) -> None:
        in_conversations = (
            await collection_multi_turn_conversations.count_documents(
                {"group_openid": group_openid}
            )
            != 0
        )
        more_content = (
            "正在进行连续对话。" if in_conversations else "没有在进行连续对话。"
        )
        await reply_group_message(
            group_openid=group_openid,
            message_id=message_id,
            content="数据库正常。" + more_content,
        )

    @command("连续对话")
    async def start_conversation(
        self,
        content: str,
        /,
        *,
        group_openid: str,
        message_id: str,
        **_: Any,
    ) -> None:
        if await collection_multi_turn_conversations.count_documents(
            {"group_openid": group_openid}
        ):
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="正在进行连续对话。",
            )
        else:
            await collection_multi_turn_conversations.insert_one(
                {"group_openid": group_openid, "contents": []}
            )
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="好的，我们来聊些什么呢？",
            )

    @command("结束对话")
    async def end_conversation(
        self,
        content: str,
        /,
        *,
        group_openid: str,
        message_id: str,
        **_: Any,
    ) -> None:
        if document := await collection_multi_turn_conversations.find_one_and_delete(
            {"group_openid": group_openid}
        ):
            await collection_messages.insert_one(
                {
                    "group_openid": group_openid,
                    "contents": document["contents"],
                    "created_at": datetime.datetime.now(),
                }
            )
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="那下次再和派蒙聊天吧。",
            )
        else:
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="我们没有在聊天啊。",
            )

    async def unknown_command(
        self,
        content: str,
        /,
        *,
        group_openid: str,
        message_id: str,
        event: Event,
        **_: Any,
    ) -> None:
        parts: list[GeminiRequestPart] = [{"text": content}]
        for attachment in event.get("d", {}).get("attachments", []):
            content_type = attachment["content_type"]
            url = attachment["url"]
            if is_supported_mime_type(content_type):
                image_base64 = await download_image(url)
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": content_type,
                            "data": image_base64,
                        }
                    }
                )
        contents: list[GeminiRequestContent]
        if document := await collection_multi_turn_conversations.find_one(
            {"group_openid": group_openid}
        ):
            contents = document["contents"]
            contents.append({"role": "user", "parts": parts})
        else:
            contents = [{"parts": parts}]

        try:
            response_content = await generate_content(contents)
        except GenerateSafeError as error:
            response_content = "这是不可以谈的话题。"
            logger.warning(f"Safe error: {error}")
        except GenerateResponseError as error:
            response_content = error.message
            logger.exception(f"Response error: {error}")
        except GenerateNetworkError as error:
            response_content = "怎么办？怎么办？派蒙连接不上提瓦特了。"
            logger.warning(f"Network error: {error}")
        else:
            update_result = await collection_multi_turn_conversations.update_one(
                {"group_openid": group_openid},
                {
                    "$push": {
                        "contents": [
                            {"role": "user", "parts": parts},
                            {
                                "role": "model",
                                "parts": [{"text": response_content}],
                            },
                        ]
                    }
                },
            )
            if update_result.modified_count == 0:
                contents.append(
                    {
                        "role": "model",
                        "parts": [{"text": response_content}],
                    },
                )
                await collection_messages.insert_one(
                    {
                        "group_openid": group_openid,
                        "contents": contents,
                        "created_at": datetime.datetime.now(),
                    }
                )
        await reply_group_message(
            group_openid=group_openid,
            message_id=message_id,
            content=response_content,
        )


async def group_at_message_create(event: Event):
    if "d" not in event:
        logger.warning(f"Unexpected event: {event}")
        return
    logger.debug(f"Group at message create: {event}")
    group_openid = event["d"]["group_openid"]
    content = event["d"]["content"]
    message_id = event["d"]["id"]
    await Commands(
        content, group_openid=group_openid, message_id=message_id, event=event
    )


async def main():
    semaphore = asyncio.Semaphore(1000)

    async with (
        initial_openapi_client(BOT_URL, AUTHORIZATION),
        initial_gemini_client(
            GEMINI_PRO_KEY, pro_url=GEMINI_PRO_URL, pro_vision_url=GEMINI_PRO_VISION_URL
        ),
    ):
        async for event in fetch_events(
            await get_gateway_url(BOT_URL, AUTHORIZATION),
            authorization=AUTHORIZATION,
            intents=0 | (1 << 30) | (1 << 25) | (1 << 12) | (1 << 0) | (1 << 1),
        ):
            op = event["op"]
            if op != 0:
                logger.warning(f"Unexpected event: {event}")
                continue

            match event.get("t"):
                case "GROUP_AT_MESSAGE_CREATE":
                    await semaphore.acquire()
                    task = asyncio.create_task(group_at_message_create(event))
                    task.add_done_callback(
                        lambda future: semaphore.release() or future.result()
                    )
                case _:
                    logger.warning(f"Unhandled event: {event}")


if __name__ == "__main__":
    logger.remove()

    import sys

    logger.add(sys.stdout, level="INFO")

    asyncio.run(main())
