from datetime import datetime

from sqlalchemy import Boolean, DateTime, Double, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import new_id


class Outlet(Base):
    __tablename__ = "outlets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(255), default="")
    lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    lng: Mapped[float | None] = mapped_column(Double, nullable=True)
    radius_m: Mapped[int] = mapped_column(default=100)  # radius geofence absensi
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
