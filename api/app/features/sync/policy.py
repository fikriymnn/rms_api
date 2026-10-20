from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.features.users.models import User
from app.features.users.roles import Role
from .dbrules import receipt_precheck

ALL = frozenset(r.value for r in Role)
OWNER = frozenset({Role.owner.value})
MGMT = frozenset({Role.owner.value, Role.manager.value})
CHEF = frozenset({Role.head_chef.value})
SALES = MGMT | {Role.cashier.value}
FRONT = SALES | {Role.waiter.value}
INVENTORY = MGMT | {Role.warehouse.value}
KITCHEN_SEES = FRONT | {Role.kitchen.value, Role.head_chef.value}
RECIPE_READ = MGMT | CHEF
PURCHASING = INVENTORY | CHEF  # owner, manager, gudang, head chef
NOBODY: frozenset[str] = frozenset()  # hanya server yang menulis

# (actor, data baru, data lama atau None) -> pesan penolakan atau None
Check = Callable[[User, dict, dict | None], str | None]


@dataclass(frozen=True)
class Spec:
    scope: Literal["shared", "outlet"]  # shared = dipakai semua outlet
    read: frozenset[str]
    write: frozenset[str]
    append_only: bool = False
    check: Check | None = None
    read_filter: Callable[[User, dict], bool] | None = None
    precheck: Callable[..., str | None] | None = None  # pemeriksaan yang butuh database


def _positive(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _orders_check(actor: User, data: dict, old: dict | None) -> str | None:
    old = old or {}
    if (data.get("discount") or 0) != (
        old.get("discount") or 0
    ) and actor.role not in MGMT:
        return "diskon hanya oleh manager/owner"
    if (
        data.get("status") == "refunded"
        and old.get("status") != "refunded"
        and actor.role not in MGMT
    ):
        return "refund hanya oleh manager/owner"
    return None


def _shifts_check(actor: User, data: dict, old: dict | None) -> str | None:
    if actor.role == Role.cashier.value:
        if data.get("cashierId") != actor.id or (
            old and old.get("cashierId") != actor.id
        ):
            return "shift hanya boleh diubah oleh kasir pemiliknya"
    return None


def _expenses_check(actor: User, data: dict, old: dict | None) -> str | None:
    if actor.role == Role.cashier.value:
        if data.get("fromDrawer") is not True or (
            old and old.get("fromDrawer") is not True
        ):
            return "kasir hanya boleh mencatat pengeluaran kas laci"
    return None


def _expenses_filter(actor: User, data: dict) -> bool:
    return actor.role != Role.cashier.value or data.get("fromDrawer") is True


_PROPOSAL_STATUSES = {"pending", "approved", "rejected", "withdrawn"}


def _proposal_check(actor: User, data: dict, old: dict | None) -> str | None:
    """Alur usulan menu: head chef mengajukan, hanya owner yang memutuskan."""
    status = data.get("status")
    if status not in _PROPOSAL_STATUSES:
        return "status usulan tidak valid"
    kind = data.get("kind")
    if kind not in ("new", "change"):
        return "jenis usulan tidak valid"
    if kind == "change" and not data.get("targetId"):
        return "usulan perubahan harus menyebut menu yang diubah"
    if not str(data.get("name") or "").strip():
        return "nama menu wajib diisi"
    if old is not None and old.get("status") != "pending":
        return "usulan yang sudah diputuskan tidak bisa diubah"

    if actor.role == Role.owner.value:
        if status in ("approved", "rejected"):
            if old is None or old.get("status") != "pending":
                return "hanya usulan yang menunggu yang bisa diputuskan"
            if data.get("decidedBy") != actor.id:
                return "decidedBy harus akun owner yang memutuskan"
            if status == "approved" and not _positive(data.get("finalPrice")):
                return "harga final wajib diisi saat menyetujui"
            if status == "rejected" and not str(data.get("decisionNote") or "").strip():
                return "alasan penolakan wajib diisi"
        return None

    # head chef
    if status in ("approved", "rejected"):
        return "hanya owner yang boleh memutuskan usulan"
    if data.get("finalPrice") is not None or data.get("decidedBy"):
        return "harga final hanya ditetapkan owner"
    if data.get("submittedBy") != actor.id:
        return "usulan hanya boleh diajukan atas nama sendiri"
    if old is not None and old.get("submittedBy") != actor.id:
        return "bukan usulan Anda"
    if old is None and status != "pending":
        return "usulan baru harus berstatus pending"
    return None


_PO_STATUSES = {"draft", "pending", "ordered", "closed", "cancelled", "rejected"}
_PO_LOCKED = ("lines", "supplierId", "supplierName", "number", "createdBy", "total")


def _same(a: object, b: object) -> bool:
    return (a or None) == (b or None)


def _po_check(actor: User, data: dict, old: dict | None) -> str | None:
    """Status 'pending'/'rejected' hanya diatur server (mesin persetujuan)."""
    status = data.get("status")
    if status not in _PO_STATUSES:
        return "status PO tidak valid"
    owner = actor.role == Role.owner.value
    if old is None:
        if status != "draft" and not (owner and status == "ordered"):
            return "PO baru harus berstatus draft (pengajuan lewat persetujuan)"
        if data.get("createdBy") != actor.id:
            return "PO harus dibuat atas nama Anda sendiri"
        return None
    old_status = old.get("status")
    if old_status in ("pending", "rejected"):
        return "PO sedang atau sudah melalui persetujuan: tidak dapat diubah dari perangkat"
    if old_status == "draft":
        if (
            not owner
            and not _same(old.get("createdBy"), actor.id)
            and old.get("createdBy")
        ):
            return "draft PO milik orang lain"
        allowed = {"draft", "cancelled"} | ({"ordered"} if owner else set())
        if status not in allowed:
            return "status PO tidak boleh diubah langsung"
        return None
    # sudah dipesan / ditutup / dibatalkan: isi terkunci
    for key in _PO_LOCKED:
        if not _same(data.get(key), old.get(key)):
            return "isi PO terkunci setelah disetujui"
    if status == old_status or (
        old_status == "ordered" and status in ("closed", "cancelled")
    ):
        return None
    return "perubahan status PO tidak valid"


def _stock_check(actor: User, data: dict, old: dict | None) -> str | None:
    kind = data.get("type")
    if kind == "sale":
        return "mutasi penjualan hanya dibuat oleh server"
    if kind == "purchase" and actor.role != Role.owner.value:
        return "pembelian tanpa PO hanya oleh owner; gunakan PO dan penerimaan barang"
    return None


REGISTRY: dict[str, Spec] = {
    # --- data master: dipakai bersama semua outlet ---
    "menu_items": Spec(
        "shared", ALL, OWNER
    ),  # menu aktif: hanya owner (atau lewat persetujuan)
    "menu_proposals": Spec("shared", OWNER | CHEF, OWNER | CHEF, check=_proposal_check),
    "recipes": Spec("shared", RECIPE_READ, OWNER | CHEF),
    "recipe_history": Spec(
        "shared", RECIPE_READ, NOBODY, append_only=True
    ),  # ditulis server
    "ingredients": Spec("shared", INVENTORY | CHEF, OWNER | CHEF),
    "suppliers": Spec("shared", PURCHASING, OWNER),
    # --- data per outlet ---
    "menu_availability": Spec("outlet", ALL, SALES | CHEF),
    "tables": Spec("outlet", ALL, MGMT),
    "orders": Spec("outlet", KITCHEN_SEES, FRONT, check=_orders_check),
    "item_status": Spec("outlet", KITCHEN_SEES, KITCHEN_SEES),
    "shifts": Spec("outlet", SALES, SALES, check=_shifts_check),
    "audit_logs": Spec("outlet", MGMT, FRONT, append_only=True),
    # mutasi stok: penjualan dibuat server; manual hanya oleh bagian gudang/manajemen
    "stock_moves": Spec(
        "outlet", PURCHASING, INVENTORY, append_only=True, check=_stock_check
    ),
    "goods_receipts": Spec(
        "outlet", PURCHASING, INVENTORY, append_only=True, precheck=receipt_precheck
    ),
    "supplier_payments": Spec(
        "outlet", MGMT, MGMT, append_only=True
    ),  # hutang: manager dan owner
    "purchase_orders": Spec("outlet", PURCHASING, PURCHASING, check=_po_check),
    "expenses": Spec(
        "outlet", SALES, SALES, check=_expenses_check, read_filter=_expenses_filter
    ),
    "reservations": Spec("outlet", FRONT, FRONT),
}
