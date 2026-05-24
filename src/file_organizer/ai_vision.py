from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import TypedDict


class AiProviderPreset(TypedDict):
    label: str
    api_base_url: str
    model: str
    supports_vision: bool


AI_PROVIDER_PRESETS: dict[str, AiProviderPreset] = {
    "deepseek": {
        "label": "DeepSeek",
        "api_base_url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "supports_vision": False,
    },
    "poe": {
        "label": "Poe",
        "api_base_url": "https://api.poe.com/v1/chat/completions",
        "model": "GPT-5-mini",
        "supports_vision": True,
    },
}

DEFAULT_AI_PROVIDER = "poe"
DEFAULT_AI_API_BASE_URL = AI_PROVIDER_PRESETS[DEFAULT_AI_PROVIDER]["api_base_url"]
DEFAULT_AI_MODEL = AI_PROVIDER_PRESETS[DEFAULT_AI_PROVIDER]["model"]
DEFAULT_AI_PROMPT = (
    "请识别图片中的文字，并将非中文内容翻译成中文。若图中主要是中文，请提取文字并简要概括。"
)


def ai_provider_label(provider_id: str) -> str:
    preset = AI_PROVIDER_PRESETS.get(provider_id)
    return preset["label"] if preset else AI_PROVIDER_PRESETS[DEFAULT_AI_PROVIDER]["label"]


def ai_provider_id_from_label(label: str) -> str:
    normalized = label.strip().lower()
    for provider_id, preset in AI_PROVIDER_PRESETS.items():
        if preset["label"].lower() == normalized:
            return provider_id
    return DEFAULT_AI_PROVIDER


def detect_ai_provider(api_base_url: str) -> str:
    url = api_base_url.strip().lower()
    if "poe.com" in url:
        return "poe"
    if "deepseek.com" in url:
        return "deepseek"
    return DEFAULT_AI_PROVIDER


def ai_provider_preset(provider_id: str) -> AiProviderPreset:
    return AI_PROVIDER_PRESETS.get(provider_id, AI_PROVIDER_PRESETS[DEFAULT_AI_PROVIDER])


def ai_provider_supports_vision(provider_id: str | None = None, *, api_base_url: str = "") -> bool:
    if provider_id:
        return ai_provider_preset(provider_id)["supports_vision"]
    return ai_provider_preset(detect_ai_provider(api_base_url))["supports_vision"]


VISION_UNSUPPORTED_MESSAGE = (
    "DeepSeek 官方 API 目前只支持纯文本，不能接收截图。\n"
    "截图识图请在「设置 → 截图 AI」里将 API 平台切换为 Poe，并填写 Poe API Key。"
)


def merge_api_message_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        elif item_type == "image_url":
            image_url = item.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if isinstance(url, str) and url.strip():
                parts.append(f"\n\n![]({url.strip()})\n\n")
        elif item_type == "image":
            url = item.get("url") or item.get("image")
            if isinstance(url, str) and url.strip():
                parts.append(f"\n\n![]({url.strip()})\n\n")
    return "\n\n".join(parts).strip()


def encode_image_as_data_url(image_path: Path) -> str:
    payload = image_path.read_bytes()
    encoded = base64.standard_b64encode(payload).decode("ascii")
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    elif suffix == ".webp":
        mime_type = "image/webp"
    elif suffix == ".gif":
        mime_type = "image/gif"
    else:
        mime_type = "image/png"
    return f"data:{mime_type};base64,{encoded}"


def call_vision_api(
    *,
    image_path: Path,
    api_base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    provider_id: str | None = None,
    timeout: float = 90.0,
) -> str:
    api_base_url = api_base_url.strip()
    api_key = api_key.strip()
    model = model.strip()
    prompt = prompt.strip()

    if not ai_provider_supports_vision(provider_id, api_base_url=api_base_url):
        raise ValueError(VISION_UNSUPPORTED_MESSAGE)

    if not api_base_url:
        raise ValueError("请先在设置中填写 API 地址。")
    if not api_key:
        raise ValueError("请先在设置中填写 API Key。")
    if not model:
        raise ValueError("请先在设置中填写模型/接入点 ID。")
    if not prompt:
        raise ValueError("请先在设置中填写识图提示词。")
    if not image_path.is_file():
        raise ValueError(f"截图文件不存在：{image_path}")

    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": encode_image_as_data_url(image_path)},
                    },
                ],
            }
        ],
    }

    request = urllib.request.Request(
        api_base_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code == 400 and "image_url" in detail and "expected text" in detail:
            raise ValueError(VISION_UNSUPPORTED_MESSAGE) from error
        raise RuntimeError(f"API 请求失败（HTTP {error.code}）：{detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接 API：{error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError("API 请求超时，请稍后重试。") from error

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"API 返回格式异常：{payload}")

    message = choices[0].get("message", {})
    content = message.get("content")
    merged = merge_api_message_content(content)
    if merged:
        return merged

    raise RuntimeError(f"API 未返回可用文本：{payload}")
