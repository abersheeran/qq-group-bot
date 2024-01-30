from functools import reduce
import re
from loguru import logger

from ..core import BotClient

__all__ = ("reply_group_message",)


async def _reply_group_message(
    *,
    group_openid: str,
    message_id: str,
    content: str,
    image_url: str | None = None,
) -> bool | None:
    bot_client = BotClient.get()

    if image_url:
        resp = await bot_client.post(
            f"/v2/groups/{group_openid}/files",
            json={"file_type": 1, "url": image_url, "srv_send_msg": False},
        )
        upload_res = resp.json()
        try:
            file_info = upload_res["file_info"]
        except KeyError:
            logger.warning(f"Failed to upload image: {resp.status_code} {upload_res}")
            request_json = {
                "msg_type": 0,
                "content": f"图片上传失败, 请访问 {image_url.replace('.', '%2E')} 查看图片",
                "msg_id": message_id,
            }
        else:
            request_json = {
                "msg_type": 7,
                "content": content,
                "msg_id": message_id,
                "media": {"file_info": file_info},
            }
    else:
        request_json = {
            "msg_type": 0,
            "content": content,
            "msg_id": message_id,
        }

    logger.debug(f"Sending message to group {group_openid}: {request_json}")
    resp = await bot_client.post(
        f"/v2/groups/{group_openid}/messages", json=request_json
    )
    if not resp.is_success:
        logger.warning(f"Failed to send message: {resp.text}")
    else:
        response_json = resp.json()
        logger.debug(f"Sent message response: {response_json}")
        res = response_json.get("msg") is None or response_json.get("msg") == "success"
        if res:
            return res
        matched = re.match(r"url not allowed:(?P<urls>.+)", response_json.get("msg"))
        if not matched:
            return res
        urls = matched.group("urls").split(",")
        logger.warning(f"Url not allowed: {urls}")
        return await _reply_group_message(
            group_openid=group_openid,
            message_id=message_id,
            content=reduce(
                lambda c, u: c.replace(u, u.replace(".", " .")), urls, content
            ),
            image_url=image_url,
        )


async def reply_group_message(
    *,
    group_openid: str,
    message_id: str,
    content: str,
    image_url: str | None = None,
) -> None:
    match await _reply_group_message(
        group_openid=group_openid,
        message_id=message_id,
        content=content,
        image_url=image_url,
    ):
        case False:
            await _reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="腾讯不让我发这条消息, 我们换个话题吧。",
            )
        case None:
            await _reply_group_message(
                group_openid=group_openid,
                message_id=message_id,
                content="不利于团结的话不要讲！",
            )
