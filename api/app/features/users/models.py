from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import new_id
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[str] = mapped_column(
        String(20)
    )  # owner|manager|cashier|waiter|kitchen|warehouse
    outlet_id: Mapped[str | None] = mapped_column(
        ForeignKey("outlets.id"), nullable=True
    )  # kosong = owner
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    attendance_consent_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attendance_consent_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
