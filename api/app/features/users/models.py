from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import new_id


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
