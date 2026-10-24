from typing import Any, Literal

from pydantic import BaseModel, Field


class SupplierData(BaseModel):
    action: Literal["create", "update"]
    supplier_id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(default="", max_length=50)
    note: str = Field(default="", max_length=255)


class ApprovalCreate(BaseModel):
    type: Literal["purchase_order", "supplier"]
    ref_id: str | None = Field(default=None, max_length=128)  # purchase_order: id PO
    supplier: SupplierData | None = None  # supplier: data usulan


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=255)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=255)  # alasan penolakan wajib


class ApprovalOut(BaseModel):
    id: str
    type: str
    outlet_id: str
    outlet_name: str
    requested_by: str
    requested_by_name: str
    title: str
    payload: dict[str, Any]
    status: str
    l1_by_name: str | None
    l1_at: int | None
    l1_note: str
    owner_by_name: str | None
    owner_at: int | None
    owner_note: str
    created_at: int
    updated_at: int
    can_approve: bool
    can_reject: bool
    can_withdraw: bool


class ApprovalCounts(BaseModel):
    inbox: int
    mine_open: int
