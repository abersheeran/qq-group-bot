from contextlib import asynccontextmanager
import contextvars
from typing import Literal, TypedDict, NotRequired

import httpx
from loguru import logger

from . import GenerateNetworkError, GenerateResponseError, GenerateSafeError


def is_supported_mime_type(mime_type: str) -> bool:
    return mime_type in (
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/heic",
        "image/heif",
    )


GeminiClient: contextvars.ContextVar[httpx.AsyncClient] = contextvars.ContextVar(
    "GeminiClient"
)


@asynccontextmanager
async def initial_gemini_client(
    key: str,
    *,
    pro_url: str | None = None,
    pro_vision_url: str | None = None,
):
    global GEMINI_PRO_URL, GEMINI_PRO_VISION_URL
    GEMINI_PRO_URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
        if pro_url is None
        else pro_url
    )
    GEMINI_PRO_VISION_URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent"
        if pro_vision_url is None
        else pro_vision_url
    )

    async with httpx.AsyncClient(params={"key": key}) as client:
        token = GeminiClient.set(client)
        try:
            yield client
        finally:
            GeminiClient.reset(token)


class InlineData(TypedDict):
    data: str
    # image/png, image/jpeg, image/webp, image/heic, or image/heif
    mime_type: Literal[
        "image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"
    ]


class Part(TypedDict, total=False):
    text: str
    inline_data: InlineData


class Content(TypedDict):
    parts: list[Part]
    role: NotRequired[Literal["user", "model"]]


async def generate_content(
    contents: list[Content],
    *,
    safety_threshold: Literal[
        "BLOCK_NONE",
        "BLOCK_ONLY_HIGH",
        "BLOCK_MEDIUM_AND_ABOVE",
        "BLOCK_LOW_AND_ABOVE",
    ] = "BLOCK_NONE",
) -> str:
    client = GeminiClient.get()

    use_vision = False
    for content in contents:
        for part in content["parts"]:
            if "inline_data" in part:
                use_vision = True
                break
    if len(contents) > 2:
        use_vision = False
        for content in contents:
            for part in tuple(content["parts"]):
                if "inline_data" in part:
                    content["parts"].remove(part)

    url = GEMINI_PRO_VISION_URL if use_vision else GEMINI_PRO_URL

    logger.debug(f"Generating content from {url} with {contents}")
    try:
        resp = await client.post(
            url,
            json={
                "contents": contents,
                "generationConfig": {
                    "stopSequences": ["Title"],
                    "temperature": 0.7,
                    "maxOutputTokens": 800,
                    "topP": 0.8,
                    "topK": 10,
                },
                "safetySettings": [
                    {"category": category, "threshold": "BLOCK_NONE"}
                    for category in (
                        "HARM_CATEGORY_HARASSMENT",
                        "HARM_CATEGORY_HATE_SPEECH",
                        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        "HARM_CATEGORY_DANGEROUS_CONTENT",
                    )
                ],
            },
            timeout=None,
        )
    except httpx.HTTPError as error:
        raise GenerateNetworkError(error)
    else:
        response_json = resp.json()
        if not resp.is_success:
            raise GenerateResponseError(
                response_json.get("error", {}).get("message", "内部错误————嘎嘎————"),
                resp,
            )
        else:
            candidates = response_json.get("candidates", None)
            if candidates is None:
                raise GenerateSafeError(resp)

            try:
                text = "".join(
                    map(
                        lambda x: x["text"],
                        candidates[0]["content"]["parts"],
                    )
                )
                logger.debug(f"Generated content: {text}")
                return text
            except KeyError:
                raise GenerateResponseError("内部错误————嘎嘎————", resp)
