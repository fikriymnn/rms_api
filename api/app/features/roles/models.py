from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RoleDef(Base):
    """Master data role. `key` dipakai sebagai nilai users.role."""

    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # staff = boleh dikelola manager outlet (membuat/mengubah akunnya)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_key: Mapped[str] = mapped_column(
        ForeignKey("roles.key", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[str] = mapped_column(String(60), primary_key=True)
