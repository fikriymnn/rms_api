from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Doc(Base):
    """Seluruh data bisnis aplikasi (order, stok, biaya, dst) sebagai dokumen JSON."""

    __tablename__ = "docs"

    collection: Mapped[str] = mapped_column(String(40), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    outlet_id: Mapped[str | None] = mapped_column(
        ForeignKey("outlets.id"), nullable=True
    )  # kosong = bersama
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[int] = mapped_column(
        BigInteger
    )  # jam klien, "yang terbaru menang"
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    seq: Mapped[int] = mapped_column(BigInteger)  # urutan dari server, kursor sinkron

    __table_args__ = (Index("idx_outlet_seq", "outlet_id", "seq"),)


class Counter(Base):
    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    v: Mapped[int] = mapped_column(BigInteger, default=0)
