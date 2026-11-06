from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.users.models import User

from .models import Doc

_TOLERANCE = 1.1  # penerimaan boleh sampai 110% dari jumlah dipesan


def _num(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _received_so_far(
    db: Session, po_id: str, outlet: str | None, exclude_id: str
) -> dict[str, float]:
    rows = db.scalars(
        select(Doc).where(
            Doc.collection == "goods_receipts",
            Doc.outlet_id == outlet,
            Doc.deleted.is_(False),
            Doc.id != exclude_id,
            Doc.data["poId"].as_string() == po_id,
        )
    )
    total: dict[str, float] = {}
    for d in rows:
        for ln in d.data.get("lines") or []:
            if isinstance(ln, dict) and ln.get("ingredientId"):
                ing = str(ln["ingredientId"])
                total[ing] = total.get(ing, 0.0) + _num(ln.get("qty"))
    return total


def receipt_precheck(
    db: Session,
    actor: User,
    doc_id: str,
    data: dict,
    old: dict | None,
    outlet: str | None,
) -> str | None:
    """Penerimaan barang hanya untuk PO yang sudah disetujui (status 'ordered') di outlet ini."""
    po_id = str(data.get("poId") or "")
    po = db.get(Doc, ("purchase_orders", po_id)) if po_id else None
    if po is None or po.deleted or po.outlet_id != outlet:
        return "penerimaan harus merujuk PO yang ada di outlet ini"
    if po.data.get("status") != "ordered":
        return "PO belum disetujui atau sudah ditutup"
    if data.get("supplierId") != po.data.get("supplierId"):
        return "supplier penerimaan tidak sesuai PO"
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        return "penerimaan tidak memiliki item"
    ordered = {
        str(ln["ingredientId"]): _num(ln.get("qty"))
        for ln in (po.data.get("lines") or [])
        if isinstance(ln, dict) and ln.get("ingredientId")
    }
    received = _received_so_far(db, po_id, outlet, doc_id)
    for ln in lines:
        ing = str(ln.get("ingredientId") or "") if isinstance(ln, dict) else ""
        qty = _num(ln.get("qty")) if isinstance(ln, dict) else 0.0
        if ing not in ordered:
            return "bahan tidak ada di PO"
        if qty <= 0:
            return "jumlah diterima harus lebih dari nol"
        if received.get(ing, 0.0) + qty > ordered[ing] * _TOLERANCE + 1e-9:
            return "jumlah diterima melebihi PO (toleransi 10%)"
    return None
