from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import new_id


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("idx_appr_status_outlet", "status", "outlet_id"),
        Index("idx_appr_requester", "requested_by"),
        Index("idx_appr_ref", "type", "ref_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(20))  # purchase_order | supplier
    outlet_id: Mapped[str] = mapped_column(ForeignKey("outlets.id"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    ref_id: Mapped[str] = mapped_column(String(128))  # id PO atau id supplier
    title: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON)  # salinan isi saat diajukan
    status: Mapped[str] = mapped_column(
        String(16)
    )  # pending_l1|pending_owner|approved|rejected|withdrawn
    l1_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    l1_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    l1_note: Mapped[str] = mapped_column(String(255), default="")
    owner_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    owner_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    owner_note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)
