from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.features.users.models import User
from app.features.users.roles import Role

ALL = frozenset(r.value for r in Role)
OWNER = frozenset({Role.owner.value})
MGMT = frozenset({Role.owner.value, Role.manager.value})
SALES = MGMT | {Role.cashier.value}
FRONT = SALES | {Role.waiter.value}
INVENTORY = MGMT | {Role.warehouse.value}
KITCHEN_SEES = FRONT | {Role.kitchen.value}

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


def _stock_check(actor: User, data: dict, old: dict | None) -> str | None:
    if actor.role not in INVENTORY and data.get("type") != "sale":
        return "kasir hanya boleh mencatat mutasi penjualan"
    return None


def _expenses_filter(actor: User, data: dict) -> bool:
    return actor.role != Role.cashier.value or data.get("fromDrawer") is True


REGISTRY: dict[str, Spec] = {
    # --- data master: dikelola owner, dipakai bersama semua outlet ---
    "menu_items": Spec("shared", ALL, OWNER),
    "recipes": Spec("shared", ALL, OWNER),
    "ingredients": Spec("shared", INVENTORY, OWNER),
    "suppliers": Spec("shared", INVENTORY, OWNER),
    # --- data per outlet ---
    "menu_availability": Spec("outlet", ALL, SALES),
    "tables": Spec("outlet", ALL, MGMT),
    "orders": Spec("outlet", KITCHEN_SEES, FRONT, check=_orders_check),
    "item_status": Spec("outlet", KITCHEN_SEES, KITCHEN_SEES),
    "shifts": Spec("outlet", SALES, SALES, check=_shifts_check),
    "audit_logs": Spec("outlet", MGMT, FRONT, append_only=True),
    "stock_moves": Spec(
        "outlet",
        INVENTORY,
        INVENTORY | {Role.cashier.value},
        append_only=True,
        check=_stock_check,
    ),
    "goods_receipts": Spec("outlet", INVENTORY, INVENTORY, append_only=True),
    "supplier_payments": Spec("outlet", INVENTORY, INVENTORY, append_only=True),
    "purchase_orders": Spec("outlet", INVENTORY, INVENTORY),
    "expenses": Spec(
        "outlet", SALES, SALES, check=_expenses_check, read_filter=_expenses_filter
    ),
    "reservations": Spec("outlet", FRONT, FRONT),
}
