from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, TypeVar

import httpx
import certifi
from pydantic import BaseModel, ValidationError

try:
    from fireworks import AsyncFireworks
except ImportError:  # pragma: no cover - optional dependency during transition
    AsyncFireworks = None

T = TypeVar("T", bound=BaseModel)

FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY", "")
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
# Default chat model: Qwen 3.6 Plus — strong reasoning + vision, available on Fireworks.
# Override via FIREWORKS_MODEL env var if needed.
DEFAULT_MODEL = os.getenv("FIREWORKS_MODEL", "accounts/fireworks/models/qwen3p6-plus")

_sdk_client: AsyncFireworks | None = None


def _headers() -> dict[str, str]:
    key = FIREWORKS_API_KEY or os.getenv("FIREWORKS_API_KEY", "")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }


def _messages(messages: list[dict], system: str | None) -> list[dict[str, str]]:
    payload_messages: list[dict[str, str]] = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(
        {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))}
        for item in messages
    )
    return payload_messages


def _openai_response_format(response_format: str | dict | None) -> dict[str, Any] | None:
    if response_format is None:
        return None
    if isinstance(response_format, dict):
        return response_format
    if str(response_format).lower() == "json":
        return {"type": "json_object"}
    return None


def _get_sdk_client() -> AsyncFireworks | None:
    global _sdk_client

    if AsyncFireworks is None:
        return None

    key = FIREWORKS_API_KEY or os.getenv("FIREWORKS_API_KEY", "")
    if not key:
        return None

    if _sdk_client is None:
        # Prefer the official async SDK for non-streaming calls because it
        # handles connection pooling and retries better than ad hoc wrappers.
        _sdk_client = AsyncFireworks(api_key=key, base_url=FIREWORKS_BASE_URL)
    return _sdk_client


def _extract_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
                continue
            if isinstance(item, dict):
                value = item.get("text")
                if value:
                    parts.append(str(value))
        return "".join(parts).strip()
    return str(content).strip()


async def chat_once(
    messages: list[dict],
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 300,
    temperature: float = 0.2,
    response_format: str | dict | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages(messages, system),
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    normalized_format = _openai_response_format(response_format)
    if normalized_format is not None:
        payload["response_format"] = normalized_format

    sdk_client = _get_sdk_client()
    if sdk_client is not None:
        response = await sdk_client.chat.completions.create(**payload)
        return _extract_content(response.choices[0].message)

    async with httpx.AsyncClient(timeout=60, verify=certifi.where()) as client:
        response = await client.post(
            f"{FIREWORKS_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
    data = response.json()
    message = (data.get("choices") or [{}])[0].get("message") or {}
    content = message.get("content") or message.get("reasoning_content", "")
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
    return str(content).strip()


async def chat_stream(
    messages: list[dict],
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 400,
    temperature: float = 0.35,
) -> AsyncGenerator[str, None]:
    payload_messages = _messages(messages, system)

    # Keep explicit SSE handling for streaming until we standardize the SDK
    # path for streamed chunks across the rest of the app.
    async with httpx.AsyncClient(timeout=60, verify=certifi.where()) as client:
        async with client.stream(
            "POST",
            f"{FIREWORKS_BASE_URL}/chat/completions",
            headers=_headers(),
            json={
                "model": model,
                "messages": payload_messages,
                "stream": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if data_text == "[DONE]":
                    break
                data = json.loads(data_text)
                delta = ((data.get("choices") or [{}])[0].get("delta") or {})
                # Normal content (most models)
                content = delta.get("content", "")
                # Reasoning content (DeepSeek, Kimi K2.6, QwQ, etc.)
                if not content:
                    content = delta.get("reasoning_content", "")
                if isinstance(content, list):
                    content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
                if content:
                    yield str(content)


async def chat_structured(
    messages: list[dict],
    schema: type[T],
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 300,
    temperature: float = 0.1,
) -> T | None:
    """Call the model with a pydantic schema as response_format.

    Returns a validated instance, or None if the model output fails to parse
    (malformed JSON or schema mismatch). Callers should handle None as "fall
    back to whatever default behavior makes sense for this call site".
    """
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "schema": schema.model_json_schema(),
        },
    }
    raw = await chat_once(
        messages,
        system=system,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )
    try:
        return schema.model_validate_json(raw)
    except (ValidationError, ValueError):
        return None
