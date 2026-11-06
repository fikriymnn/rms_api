from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    func,
)
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
    # jadwal buka-tutup: zona waktu dan aturan penilaian ketepatan absensi
    timezone: Mapped[str] = mapped_column(
        String(40), default="Asia/Jakarta", server_default="Asia/Jakarta"
    )
    staff_lead_min: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )  # staf diharapkan hadir sekian menit sebelum buka
    staff_tail_min: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )  # staf diharapkan pulang sekian menit setelah tutup
    grace_min: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5"
    )  # toleransi terlambat / pulang cepat


class OutletHours(Base):
    """Jam buka-tutup satu outlet pada satu hari dalam seminggu (0 = Senin)."""

    __tablename__ = "outlet_hours"

    outlet_id: Mapped[str] = mapped_column(
        ForeignKey("outlets.id", ondelete="CASCADE"), primary_key=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    open_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # menit sejak 00:00
    close_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # <= open_min = lewat tengah malam
