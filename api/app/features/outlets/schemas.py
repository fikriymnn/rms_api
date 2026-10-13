from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OutletBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(default="", max_length=255)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=100, ge=20, le=2000)


class OutletCreate(OutletBase):
    pass


class OutletUpdate(BaseModel):
    """Semua opsional: hanya kolom yang dikirim yang diubah (PATCH)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=20, le=2000)
    active: bool | None = None


class OutletOut(OutletBase):
    model_config = ConfigDict(from_attributes=True)  # boleh dibuat dari objek ORM

    id: str
    active: bool
    created_at: datetime
