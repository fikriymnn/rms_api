from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.features.roles.service import can, has_any
from app.features.users.models import User
from .dbrules import receipt_precheck

Perms = tuple[str, ...]  # lolos jika user memegang SALAH SATU izin
NOBODY: Perms = ()  # tidak ada yang boleh: hanya server yang menulis

# (actor, data baru, data lama atau None) -> pesan penolakan atau None
Check = Callable[[User, dict, dict | None], str | None]


@dataclass(frozen=True)
class Spec:
    scope: Literal["shared", "outlet"]  # shared = dipakai semua outlet
    read: Perms
    create: Perms = ()
    update: Perms = ()
    delete: Perms = ()
    append_only: bool = False
    check: Check | None = None
    read_filter: Callable[[User, dict], bool] | None = None
    precheck: Callable[..., str | None] | None = None  # pemeriksaan yang butuh database


def crud(feature: str, **override: Perms) -> dict[str, Perms]:
    """read/create/update/delete = izin "<fitur>.<aksi>"; bisa ditimpa per aksi."""
    base = {a: (f"{feature}.{a}",) for a in ("read", "create", "update", "delete")}
    return base | override


def any_write(spec: "Spec") -> Perms:
    return spec.create + spec.update + spec.delete


def op_perms(spec: "Spec", *, is_new: bool, deleting: bool) -> Perms:
    if spec.append_only:  # kirim ulang yang identik tetap sah bagi pembuatnya
        return spec.create
    if deleting:
        return spec.delete
    return spec.create if is_new else spec.update


def _positive(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _orders_check(actor: User, data: dict, old: dict | None) -> str | None:
    old = old or {}
    if (data.get("discount") or 0) != (old.get("discount") or 0) and not can(
        actor, "orders.discount"
    ):
        return "diskon hanya oleh role yang berhak"
    if (
        data.get("status") == "refunded"
        and old.get("status") != "refunded"
        and not can(actor, "orders.refund")
    ):
        return "refund hanya oleh role yang berhak"
    return None


def _shifts_check(actor: User, data: dict, old: dict | None) -> str | None:
    if not can(actor, "shifts.manage_all"):
        if data.get("cashierId") != actor.id or (
            old and old.get("cashierId") != actor.id
        ):
            return "shift hanya boleh diubah oleh kasir pemiliknya"
    return None


def _expenses_check(actor: User, data: dict, old: dict | None) -> str | None:
    if not can(actor, "expenses.manage_all"):
        if data.get("fromDrawer") is not True or (
            old and old.get("fromDrawer") is not True
        ):
            return "kasir hanya boleh mencatat pengeluaran kas laci"
    return None


def _expenses_filter(actor: User, data: dict) -> bool:
    return can(actor, "expenses.manage_all") or data.get("fromDrawer") is True


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

    if can(actor, "proposals.decide"):
        if status in ("approved", "rejected"):
            if old is None or old.get("status") != "pending":
                return "hanya usulan yang menunggu yang bisa diputuskan"
            if data.get("decidedBy") != actor.id:
                return "decidedBy harus akun yang memutuskan"
            if status == "approved" and not _positive(data.get("finalPrice")):
                return "harga final wajib diisi saat menyetujui"
            if status == "rejected" and not str(data.get("decisionNote") or "").strip():
                return "alasan penolakan wajib diisi"
        return None

    # pengaju (mis. head chef)
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
    owner = can(actor, "purchase_orders.direct_order")
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
    if kind == "purchase" and not can(actor, "stock.purchase_direct"):
        return "pembelian tanpa PO butuh izin khusus; gunakan PO dan penerimaan barang"
    return None


REGISTRY: dict[str, Spec] = {
    # --- data master: dipakai bersama semua outlet ---
    "menu_items": Spec("shared", **crud("menu")),
    "menu_proposals": Spec(
        "shared",
        read=("proposals.read",),
        create=("proposals.create",),
        update=("proposals.update", "proposals.decide"),
        delete=("proposals.update", "proposals.decide"),
        check=_proposal_check,
    ),
    "recipes": Spec("shared", **crud("recipes")),
    "recipe_history": Spec("shared", read=("recipes.read",), append_only=True),
    "ingredients": Spec("shared", **crud("ingredients")),
    "suppliers": Spec("shared", **crud("suppliers")),
    # --- data per outlet ---
    "menu_availability": Spec(
        "outlet",
        read=("menu.read",),
        create=("menu.availability",),
        update=("menu.availability",),
        delete=("menu.availability",),
    ),
    "tables": Spec("outlet", **crud("tables")),
    # kasir/waiter/dapur melihat pesanan; status per item ikut izin pesanan/dapur
    "orders": Spec("outlet", **crud("orders"), check=_orders_check),
    "item_status": Spec(
        "outlet",
        read=("orders.read", "kitchen.read"),
        create=("kitchen.update", "orders.update"),
        update=("kitchen.update", "orders.update"),
        delete=("kitchen.update", "orders.update"),
    ),
    "shifts": Spec(
        "outlet",
        read=("shifts.read",),
        create=("shifts.create",),
        update=("shifts.update",),
        delete=("shifts.update",),
        check=_shifts_check,
    ),
    "audit_logs": Spec(
        "outlet", read=("audit.read",), create=("audit.create",), append_only=True
    ),
    # mutasi stok: penjualan dibuat server; manual hanya yang berizin
    "stock_moves": Spec(
        "outlet",
        read=("stock.read",),
        create=("stock.create",),
        append_only=True,
        check=_stock_check,
    ),
    "goods_receipts": Spec(
        "outlet",
        read=("goods_receipts.read",),
        create=("goods_receipts.create",),
        append_only=True,
        precheck=receipt_precheck,
    ),
    "supplier_payments": Spec(
        "outlet",
        read=("supplier_payments.read",),
        create=("supplier_payments.create",),
        append_only=True,
    ),
    "purchase_orders": Spec("outlet", **crud("purchase_orders"), check=_po_check),
    "expenses": Spec(
        "outlet",
        **crud("expenses"),
        check=_expenses_check,
        read_filter=_expenses_filter,
    ),
    "reservations": Spec("outlet", **crud("reservations")),
    "table_holds": Spec(
        "outlet",
        read=("tables.hold",),
        create=("tables.hold",),
        update=("tables.hold",),
        delete=("tables.hold",),
    ),
}
