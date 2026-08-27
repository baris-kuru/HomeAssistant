from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SearchRequest(BaseModel):
    query: str | None = None
    queries: list[str] | None = None
    max_results: int | None = Field(default=None, ge=1, le=20)
    include_pages: bool = True
    lane: Literal["fast", "search", "deep"] = "search"


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str = "tr"


class SettingsUpdate(BaseModel):
    language: str | None = None
    briefing_time: str | None = None
    briefing_on_weekends: bool | None = None
    timezone: str | None = None
    notifications_enabled: bool | None = None


class ConsolidateRequest(BaseModel):
    entity: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    memory_ids: list[int] = Field(min_length=1)


class VisionRequest(BaseModel):
    image: str

    @field_validator("image")
    @classmethod
    def _must_be_data_uri(cls, value: str) -> str:
        if not value.startswith("data:image/"):
            raise ValueError("image must be a data:image/... URI")
        if "," not in value:
            raise ValueError("image data URI is malformed")
        return value


class RouteResponse(BaseModel):
    """Shape returned by the LLM router. Unknown values get coerced back to defaults."""

    lane: Literal["fast", "search", "deep"] = "fast"
    domain: Literal["calendar", "weather", "memory", "documents", "general", "identity", "devices"] = "general"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    reason: str = "LLM-based routing"
