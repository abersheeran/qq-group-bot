import asyncio
import base64
import datetime
import os
import random
from typing import Any
import httpx

from loguru import logger
from motor.motor_asyncio import AsyncIOMotorClient
from bingimagecreator import ImageGen, GenerateImagePromptException

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

BING_COOKIES = os.environ["BING_COOKIES"]


async def download_image(url: str) -> str:
    async with httpx.AsyncClient() as client:
        return base64.b64encode(await (await client.get(url)).aread()).decode()


async def generate_image(prompt: str) -> str:
    async with ImageGen(BING_COOKIES) as g:
        links = await g.get_images(prompt)
        logger.debug(f"Generated images: {links}")
        # QQ 只能发 1 张图
        return str(g.session._merge_url(random.choice(links)))


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

    @command("画图")
    async def draw(
        self,
        prompt: str,
        /,
        *,
        group_openid: str,
        message_id: str,
        event: Event,
        **_: Any,
    ) -> None:
        if not prompt:
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="你要我画什么呢？",
            )
            return

        parts: list[Any] = [
            {
                "text": "Please generate accurate and detailed prompt for DALL-E based on the prompt words I gave. You only need to give me the prompt and do not give any additional content. I'll give you a big tip: "
                + prompt
            }
        ]
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
        try:
            image_prompt = await generate_content(
                [{"parts": parts}], safety_threshold="BLOCK_LOW_AND_ABOVE"
            )
            image_url = await generate_image(image_prompt)
        except (GenerateImagePromptException, GenerateSafeError):
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="这个不可以画哦。",
            )
            return
        except GenerateNetworkError as error:
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="怎么办？怎么办？派蒙连接不上提瓦特了。",
            )
            logger.warning(f"Network error: {error}")
            return
        except GenerateResponseError as error:
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content=str(error),
            )
        except Exception:
            logger.exception("Failed to generate image")
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="哎呀，颜料桶打翻了。",
            )
            return
        else:
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content=f"这是你要的画。使用了“{image_prompt}”",
                image_url=image_url,
            )

    @command("Bing cookies")
    async def bing_cookies(
        self,
        content: str,
        /,
        *,
        group_openid: str,
        message_id: str,
        **_: Any,
    ) -> None:
        global BING_COOKIES

        if not content:
            await reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content=BING_COOKIES,
            )
            return

        BING_COOKIES = content.strip()

        await reply_group_message(
            group_openid=group_openid,
            message_id=message_id,
            content="好的，已经更新了。",
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
                        "contents": {
                            "$each": [
                                {"role": "user", "parts": parts},
                                {
                                    "role": "model",
                                    "parts": [{"text": response_content}],
                                },
                            ]
                        }
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
    try:
        await asyncio.wait_for(
            Commands(
                content, group_openid=group_openid, message_id=message_id, event=event
            ),
            5 * 60 - 5,  # 5 minutes
        )
    except asyncio.TimeoutError:
        await reply_group_message(
            group_openid=group_openid,
            message_id=message_id,
            content="哎呀，派蒙思考太久了。",
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
            intents=0 | (1 << 0) | (1 << 1) | (1 << 12) | (1 << 25) | (1 << 30),
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

    logger.add(sys.stdout, level=os.environ.get("LOG_LEVEL", "INFO"))

    asyncio.run(main())
