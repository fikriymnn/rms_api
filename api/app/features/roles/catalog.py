"""Katalog fitur & izin. Satu izin = "fitur.aksi", mis. "menu.create".

Katalog ini ada di kode (bukan di database) karena setiap izin harus punya
penjaga di kode. Yang dinamis adalah *siapa* memegang izin apa (tabel
role_permissions), bukan daftar izin itu sendiri.
"""

from dataclasses import dataclass

OWNER_KEY = "owner"


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    group: str
    actions: tuple[tuple[str, str], ...]  # (aksi, label)


_R = ("read", "Lihat")
_CRUD = (_R, ("create", "Tambah"), ("update", "Ubah"), ("delete", "Hapus"))

CATALOG: tuple[Feature, ...] = (
    Feature("dashboard", "Dashboard", "Operasional", (_R,)),
    Feature(
        "menu", "Menu", "Operasional", _CRUD + (("availability", "Atur ketersediaan"),)
    ),
    Feature(
        "tables",
        "Meja",
        "Operasional",
        _CRUD + (("hold", "Tahan meja (bayar di muka)"),),
    ),
    Feature(
        "orders",
        "Pesanan / POS",
        "Operasional",
        _CRUD
        + (
            ("pay", "Terima pembayaran"),
            ("discount", "Beri diskon"),
            ("refund", "Refund"),
            ("void_processed", "Batalkan item yang sudah diproses dapur"),
        ),
    ),
    Feature(
        "kitchen",
        "Dapur (KDS)",
        "Operasional",
        (
            _R,
            ("update", "Ubah status masak"),
            ("notify", "Terima notifikasi pesanan baru"),
        ),
    ),
    Feature(
        "shifts",
        "Kas / Shift",
        "Operasional",
        (
            _R,
            ("create", "Buka shift"),
            ("update", "Ubah / tutup shift"),
            ("manage_all", "Kelola shift milik orang lain"),
        ),
    ),
    Feature("reservations", "Reservasi", "Operasional", _CRUD),
    Feature(
        "expenses",
        "Biaya",
        "Keuangan",
        _CRUD + (("manage_all", "Semua kategori (bukan hanya kas laci)"),),
    ),
    Feature("finance", "Keuangan", "Keuangan", (_R,)),
    Feature("reports", "Laporan", "Keuangan", (_R,)),
    Feature("audit", "Log audit", "Keuangan", (_R, ("create", "Mencatat"))),
    Feature("ingredients", "Bahan", "Stok & Pembelian", _CRUD),
    Feature("recipes", "Resep", "Stok & Pembelian", _CRUD),
    Feature(
        "stock",
        "Stok",
        "Stok & Pembelian",
        (
            _R,
            ("create", "Catat mutasi stok"),
            ("purchase_direct", "Catat pembelian tanpa PO"),
        ),
    ),
    Feature("suppliers", "Supplier", "Stok & Pembelian", _CRUD),
    Feature(
        "purchase_orders",
        "Purchase Order",
        "Stok & Pembelian",
        _CRUD + (("direct_order", "Pesan langsung tanpa persetujuan"),),
    ),
    Feature(
        "goods_receipts",
        "Penerimaan barang",
        "Stok & Pembelian",
        (_R, ("create", "Catat penerimaan")),
    ),
    Feature(
        "supplier_payments",
        "Pembayaran supplier",
        "Stok & Pembelian",
        (_R, ("create", "Catat pembayaran")),
    ),
    Feature(
        "proposals",
        "Usulan menu",
        "Manajemen",
        (
            _R,
            ("create", "Ajukan"),
            ("update", "Ubah / tarik"),
            ("decide", "Putuskan (setujui / tolak)"),
        ),
    ),
    Feature(
        "approvals",
        "Persetujuan",
        "Manajemen",
        (
            _R,
            ("create", "Mengajukan"),
            ("approve_l1", "Menyetujui tingkat 1"),
            ("approve_final", "Menyetujui akhir"),
        ),
    ),
    Feature(
        "attendance",
        "Absensi",
        "Tim",
        (
            ("clock", "Absen sendiri"),
            ("read_all", "Lihat absensi tim"),
            ("correct", "Koreksi"),
            ("review", "Tinjau foto"),
        ),
    ),
    Feature(
        "users",
        "Pengguna",
        "Administrasi",
        (
            _R,
            ("create", "Tambah"),
            ("update", "Ubah"),
            ("reset_password", "Reset password"),
            ("set_active", "Aktif / nonaktifkan"),
        ),
    ),
    Feature("notifications", "Notifikasi", "Akun", (("read", "Kotak masuk"),)),
)

ALL_PERMISSIONS: frozenset[str] = frozenset(
    f"{f.key}.{a}" for f in CATALOG for a, _ in f.actions
)

# Izin yang TIDAK otomatis dimiliki owner: sifatnya "peran di alur", bukan
# kewenangan. Owner tidak absen, tidak mengajukan, tidak melompati persetujuan
# tingkat 1, dan tidak menerima notifikasi pesanan dapur.
OPT_IN = frozenset(
    {
        "kitchen.notify",
        "attendance.clock",
        "approvals.create",
        "approvals.approve_l1",
    }
)
OWNER_PERMISSIONS: frozenset[str] = ALL_PERMISSIONS - OPT_IN

# ---- peran bawaan & izin awalnya (meniru aturan lama persis) ----------------
_ALL = ("owner", "manager", "head_chef", "cashier", "waiter", "kitchen", "warehouse")
_OWN = ("owner",)
_MGMT = ("owner", "manager")
_SALES = _MGMT + ("cashier",)
_FRONT = _SALES + ("waiter",)
_INV = _MGMT + ("warehouse",)
_CHEF = ("head_chef",)
_NOT_WH = tuple(r for r in _ALL if r != "warehouse")
_PURCH = _INV + _CHEF

_GRANTS: dict[tuple[str, ...], tuple[str, ...]] = {
    _ALL: ("menu.read", "tables.read"),
    _NOT_WH: ("orders.read",),
    _FRONT: (
        "orders.create",
        "orders.update",
        "orders.delete",
        "tables.hold",
        "audit.create",
        "reservations.read",
        "reservations.create",
        "reservations.update",
        "reservations.delete",
    ),
    _MGMT: (
        "tables.create",
        "tables.update",
        "tables.delete",
        "orders.discount",
        "orders.refund",
        "orders.void_processed",
        "shifts.manage_all",
        "expenses.manage_all",
        "finance.read",
        "reports.read",
        "audit.read",
        "supplier_payments.read",
        "supplier_payments.create",
        "attendance.read_all",
        "attendance.correct",
        "attendance.review",
        "users.read",
        "users.create",
        "users.update",
        "users.reset_password",
        "users.set_active",
    ),
    _SALES: (
        "orders.pay",
        "shifts.read",
        "shifts.create",
        "shifts.update",
        "expenses.read",
        "expenses.create",
        "expenses.update",
        "expenses.delete",
        "menu.availability",
    ),
    _CHEF: ("menu.availability",),
    ("owner", "manager", "head_chef"): ("dashboard.read",),
    ("owner", "manager", "head_chef", "kitchen", "waiter"): (
        "kitchen.read",
        "kitchen.update",
    ),
    ("kitchen", "head_chef"): ("kitchen.notify",),
    _OWN: (
        "menu.create",
        "menu.update",
        "menu.delete",
        "ingredients.create",
        "ingredients.update",
        "ingredients.delete",
        "suppliers.create",
        "suppliers.update",
        "suppliers.delete",
        "stock.purchase_direct",
        "purchase_orders.direct_order",
        "proposals.decide",
        "approvals.approve_final",
    ),
    _PURCH: (
        "ingredients.read",
        "suppliers.read",
        "stock.read",
        "purchase_orders.read",
        "purchase_orders.create",
        "purchase_orders.update",
        "purchase_orders.delete",
        "goods_receipts.read",
    ),
    _INV: ("stock.create", "goods_receipts.create"),
    _MGMT + _CHEF: ("recipes.read",),
    _OWN
    + _CHEF: (
        "recipes.create",
        "recipes.update",
        "recipes.delete",
        "proposals.read",
        "proposals.create",
        "proposals.update",
    ),
    ("owner", "manager", "head_chef", "warehouse"): ("approvals.read",),
    ("warehouse", "manager", "head_chef"): ("approvals.create",),
    ("manager", "head_chef"): ("approvals.approve_l1",),
    ("manager", "head_chef", "cashier", "waiter", "kitchen", "warehouse"): (
        "attendance.clock",
    ),
    ("owner", "manager", "head_chef", "kitchen", "warehouse"): ("notifications.read",),
}


def _build_defaults() -> dict[str, frozenset[str]]:
    out: dict[str, set[str]] = {r: set() for r in _ALL}
    for roles, perms in _GRANTS.items():
        for r in roles:
            out[r].update(perms)
    out["owner"] = set(OWNER_PERMISSIONS)
    unknown = {p for s in out.values() for p in s} - ALL_PERMISSIONS
    assert not unknown, f"izin tidak ada di katalog: {unknown}"
    return {k: frozenset(v) for k, v in out.items()}


SYSTEM_DEFAULTS = _build_defaults()

# key -> (nama tampilan, deskripsi, is_staff)
SYSTEM_ROLES: dict[str, tuple[str, str, bool]] = {
    "owner": ("Owner", "Pemilik. Akses penuh, tidak bisa diubah.", False),
    "manager": ("Manager", "Mengelola operasional satu outlet.", False),
    "head_chef": ("Head Chef", "Kepala dapur: resep, usulan menu, stok.", False),
    "cashier": ("Kasir", "Menerima pembayaran dan mengelola kas laci.", True),
    "waiter": ("Waiter", "Mengambil pesanan dan mengantar.", True),
    "kitchen": ("Dapur", "Memproses pesanan di layar dapur.", True),
    "warehouse": ("Gudang", "Penerimaan barang dan stok.", True),
}


def catalog_json() -> list[dict]:
    return [
        {
            "key": f.key,
            "label": f.label,
            "group": f.group,
            "actions": [
                {"key": a, "label": lbl, "permission": f"{f.key}.{a}"}
                for a, lbl in f.actions
            ],
        }
        for f in CATALOG
    ]
