from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import new_id


class Attendance(Base):
    """Satu baris = satu sesi kerja (masuk sampai pulang)."""

    __tablename__ = "attendance"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    outlet_id: Mapped[str] = mapped_column(ForeignKey("outlets.id"))
    clock_in_at: Mapped[int] = mapped_column(BigInteger)  # epoch ms, jam perangkat
    clock_out_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    in_lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    in_lng: Mapped[float | None] = mapped_column(Double, nullable=True)
    in_accuracy: Mapped[float | None] = mapped_column(Double, nullable=True)
    in_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_photo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    in_flags: Mapped[str] = mapped_column(String(100), default="")
    in_received_at: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )  # jam server
    in_event_id: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True
    )

    out_lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    out_lng: Mapped[float | None] = mapped_column(Double, nullable=True)
    out_accuracy: Mapped[float | None] = mapped_column(Double, nullable=True)
    out_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    out_photo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    out_flags: Mapped[str] = mapped_column(String(100), default="")
    out_received_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_event_id: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True
    )

    review_status: Mapped[str] = mapped_column(
        String(12), default="pending"
    )  # pending|ok|suspicious
    review_note: Mapped[str] = mapped_column(String(255), default="")
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    edits: Mapped[list] = mapped_column(JSON, default=list)  # riwayat koreksi manager
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_att_outlet_in", "outlet_id", "clock_in_at"),
        Index("idx_att_user_in", "user_id", "clock_in_at"),
    )


class ConsentEvent(Base):
    """Bukti persetujuan dan pencabutannya. Hanya ditambah, tidak memuat data biometrik."""

    __tablename__ = "consent_events"
    __table_args__ = (Index("idx_consent_user", "user_id", "at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(10))  # granted | revoked
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    at: Mapped[int] = mapped_column(BigInteger)
    photos_deleted: Mapped[int] = mapped_column(Integer, default=0)
    by_user: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )  # pelaksana; CLI: kosong
