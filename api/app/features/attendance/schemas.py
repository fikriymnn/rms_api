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
    via_kiosk: bool = False
    # ketepatan waktu terhadap jadwal outlet (kosong = outlet belum punya jadwal hari itu)
    sched_in_at: int | None = None
    sched_out_at: int | None = None
    in_status: Literal["on_time", "late"] | None = None
    late_min: int = 0
    out_status: Literal["on_time", "early", "overtime"] | None = None
    early_out_min: int = 0
    overtime_min: int = 0


class KioskStaffOut(BaseModel):
    id: str
    name: str
    position: str
    role_name: str
    has_pin: bool
    consent_ok: bool
    clocked_in: bool


class KioskVerifyIn(BaseModel):
    user_id: str
    pin: str = Field(pattern=r"^\d{4,6}$")
    event_id: str = Field(min_length=8, max_length=36)


class KioskTicketOut(BaseModel):
    ticket: str


class KioskConsentIn(BaseModel):
    user_id: str
    ticket: str
    version: int


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4,6}$")


class PinSelfIn(PinIn):
    password: str = Field(min_length=1, max_length=200)


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ScheduleDayIn(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0 = Senin
    closed: bool = False
    open: str | None = Field(default=None, pattern=_HHMM)
    close: str | None = Field(default=None, pattern=_HHMM)


class ScheduleIn(BaseModel):
    timezone: str = Field(default="Asia/Jakarta", max_length=40)
    lead_min: int = Field(default=0, ge=0, le=240)
    tail_min: int = Field(default=0, ge=0, le=240)
    grace_min: int = Field(default=5, ge=0, le=120)
    days: list[ScheduleDayIn] = Field(max_length=7)


class ScheduleDayOut(BaseModel):
    weekday: int
    configured: bool
    closed: bool
    open: str | None
    close: str | None


class ScheduleOut(BaseModel):
    outlet_id: str
    timezone: str
    lead_min: int
    tail_min: int
    grace_min: int
    days: list[ScheduleDayOut]


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
    late_count: int = 0
    late_minutes: int = 0
    early_out_count: int = 0
    overtime_minutes: int = 0


class RevokeOut(BaseModel):
    revoked_at: int
    photos_deleted: int
