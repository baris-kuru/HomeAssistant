from __future__ import annotations

import os
from typing import Literal

import httpx
import certifi

FIREWORKS_API_KEY_ENV = "FIREWORKS_API_KEY"
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"

FLUX_MODELS: dict[str, str] = {
    "schnell": "accounts/fireworks/models/flux-1-schnell-fp8",
    "dev": "accounts/fireworks/models/flux-1-dev-fp8",
    "kontext": "accounts/fireworks/models/flux-kontext-pro",
}

Quality = Literal["schnell", "dev", "kontext"]


async def generate_flux_image(prompt: str, quality: Quality = "dev") -> bytes:
    """Generate a PNG via the Fireworks FLUX workflow endpoint.

    Raises RuntimeError on misconfiguration and httpx.HTTPStatusError on API error.
    """
    api_key = os.getenv(FIREWORKS_API_KEY_ENV, "").strip()
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY is not configured")
    if quality not in FLUX_MODELS:
        raise ValueError(f"Unknown FLUX quality '{quality}'")

    model_id = FLUX_MODELS[quality]
    body: dict[str, object] = {"prompt": prompt}
    if quality == "schnell":
        body["aspect_ratio"] = "1:1"

    async with httpx.AsyncClient(timeout=120, verify=certifi.where()) as client:
        response = await client.post(
            f"{FIREWORKS_BASE_URL}/workflows/{model_id}/text_to_image",
            headers={
                "Content-Type": "application/json",
                "Accept": "image/png",
                "Authorization": f"Bearer {api_key}",
            },
            json=body,
        )
        response.raise_for_status()
    image_bytes = response.content
    if not image_bytes:
        raise RuntimeError("Fireworks returned an empty image response")
    return image_bytes
