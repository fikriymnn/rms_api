from typing import Any

from pydantic import BaseModel, Field


class DeviceIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    platform: str = Field(default="android", max_length=16)


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str
    data: dict[str, Any]
    created_at: int
    read: bool


class UnreadOut(BaseModel):
    count: int


class ReadIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)
    all: bool = False
    ref_type: str | None = Field(
        default=None, max_length=24
    )  # order | approval | proposal
    ref_id: str | None = Field(
        default=None, max_length=128
    )  # tanpa ref_id = semua dari jenis itu
