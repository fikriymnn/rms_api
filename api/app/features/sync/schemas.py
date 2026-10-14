from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SyncDocIn(BaseModel):
    collection: str = Field(min_length=1, max_length=40)
    id: str = Field(min_length=1, max_length=128)
    data: dict[str, Any]
    updated_at: int  # jam klien (epoch ms); "yang terbaru menang"
    deleted: bool = False


class PushRequest(BaseModel):
    outlet_id: str | None = None  # hanya dipakai owner untuk memilih outlet aktif
    docs: list[SyncDocIn] = Field(min_length=1, max_length=200)


class PushResult(BaseModel):
    collection: str
    id: str
    status: Literal["ok", "stale", "rejected"]
    reason: str | None = None
    seq: int | None = None


class PushResponse(BaseModel):
    results: list[PushResult]


class SyncDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collection: str
    id: str
    outlet_id: str | None
    data: dict[str, Any]
    updated_at: int
    deleted: bool
    seq: int


class PullResponse(BaseModel):
    docs: list[SyncDocOut]
    next_since: int  # simpan ini sebagai kursor berikutnya
    has_more: bool


class CollectionsOut(BaseModel):
    read: list[str]
    write: list[str]
