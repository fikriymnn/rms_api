from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import new_id


class DeviceToken(Base):
    """Satu baris = satu perangkat (token FCM) milik satu akun yang sedang login."""

    __tablename__ = "device_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(512), unique=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")
    created_at: Mapped[int] = mapped_column(BigInteger)
    last_seen_at: Mapped[int] = mapped_column(BigInteger)


class Notification(Base):
    """Kotak masuk per penerima. Server yang menentukan siapa yang mendapat baris ini."""

    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notif_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    outlet_id: Mapped[str | None] = mapped_column(
        ForeignKey("outlets.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(24))  # approval | proposal | order
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(
        JSON
    )  # {"type": ..., "id": ...} untuk membuka layar yang tepat
    created_at: Mapped[int] = mapped_column(BigInteger)
    read_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
