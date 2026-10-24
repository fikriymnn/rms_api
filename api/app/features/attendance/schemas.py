from typing import Literal

from pydantic import BaseModel, Field


class AttendanceOut(BaseModel):
    id: str
    user_id: str
    user_name: str
    outlet_id: str
    clock_in_at: int
    clock_out_at: int | None
    minutes: int | None
    in_distance_m: int | None
    out_distance_m: int | None
    in_flags: list[str]
    out_flags: list[str]
    has_in_photo: bool
    has_out_photo: bool
    review_status: str
    review_note: str
    edited: bool
    stale: bool  # masuk lebih dari 16 jam lalu dan belum pulang


class ConsentIn(BaseModel):
    version: int


class ConsentOut(BaseModel):
    version: int
    at: int  # epoch ms, waktu server


class MeOut(BaseModel):
    open: AttendanceOut | None
    recent: list[AttendanceOut]
    consent: ConsentOut | None = None


class CorrectionIn(BaseModel):
    clock_in_at: int | None = Field(default=None, gt=0)
    clock_out_at: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=255)


class ReviewIn(BaseModel):
    status: Literal["pending", "ok", "suspicious"]
    note: str = Field(default="", max_length=255)


class SummaryRow(BaseModel):
    user_id: str
    user_name: str
    records: int
    minutes: int
    open_count: int


class RevokeOut(BaseModel):
    revoked_at: int
    photos_deleted: int
