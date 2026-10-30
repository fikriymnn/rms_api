import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import events
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.utils import new_id
from app.features.outlets.models import Outlet
from app.features.sync import service as sync_service
from app.features.sync.models import Doc
from app.features.roles.service import can
from app.features.users.models import User
from app.features.users.roles import Role

from .models import ApprovalRequest
from .schemas import (
    ApprovalCounts,
    ApprovalCreate,
    ApprovalOut,
    IngredientData,
    SupplierData,
)

PENDING = ("pending_l1", "pending_owner")
DECIDED = ("approved", "rejected", "withdrawn")


def _l1(actor: User) -> bool:
    return can(actor, "approvals.approve_l1")


def _final(actor: User) -> bool:
    return can(actor, "approvals.approve_final")


def _now() -> int:
    return int(time.time() * 1000)


def _num(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _rp(n: int) -> str:
    return "Rp " + f"{n:,}".replace(",", ".")


# ---------- siapa boleh apa ----------


def _is_l1(actor: User, req: ApprovalRequest) -> bool:
    return (
        _l1(actor)
        and actor.outlet_id == req.outlet_id
        and actor.id != req.requested_by  # tidak boleh menyetujui pengajuan sendiri
    )


def can_view(actor: User, req: ApprovalRequest) -> bool:
    return (
        actor.id == req.requested_by
        or _final(actor)
        or (_l1(actor) and actor.outlet_id == req.outlet_id)
    )


def can_approve(actor: User, req: ApprovalRequest) -> bool:
    if req.status == "pending_l1":
        return _is_l1(actor, req)  # rantai ketat: owner tidak melompati tingkat 1
    if req.status == "pending_owner":
        return _final(actor)
    return False


def can_reject(actor: User, req: ApprovalRequest) -> bool:
    if req.status == "pending_l1":
        return _is_l1(actor, req) or _final(actor)
    if req.status == "pending_owner":
        return _final(actor)
    return False


def can_withdraw(actor: User, req: ApprovalRequest) -> bool:
    return actor.id == req.requested_by and req.status in PENDING


def get_for(
    db: Session, actor: User, approval_id: str, *, lock: bool = False
) -> ApprovalRequest:
    stmt = select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    if lock:
        stmt = stmt.with_for_update()
    req = db.scalar(stmt)
    if req is None or not can_view(actor, req):
        raise NotFound("Pengajuan tidak ditemukan")  # 404: tidak membocorkan keberadaan
    return req


# ---------- menyiapkan isi pengajuan ----------


def _prepare_po(db: Session, actor: User, ref_id: str) -> tuple[dict, str]:
    if not ref_id:
        raise BadRequest("ref_id (id PO) wajib diisi")
    po = db.get(Doc, ("purchase_orders", ref_id))
    if (
        po is None
        or po.deleted
        or po.outlet_id != actor.outlet_id
        or po.data.get("createdBy") != actor.id
    ):
        raise NotFound(
            "PO tidak ditemukan di server. Simpan dan sinkronkan draf terlebih dahulu."
        )
    if po.data.get("status") != "draft":
        raise Conflict("Hanya PO berstatus draft yang bisa diajukan")
    lines = [ln for ln in (po.data.get("lines") or []) if isinstance(ln, dict)]
    if not lines or any(_num(ln.get("qty")) <= 0 for ln in lines):
        raise BadRequest("PO harus memiliki item dengan jumlah lebih dari nol")
    supplier = db.get(Doc, ("suppliers", str(po.data.get("supplierId") or "")))
    if supplier is None or supplier.deleted:
        raise BadRequest(
            "Supplier PO belum terdaftar. Ajukan supplier terlebih dahulu."
        )
    total = int(
        sum(round(_num(ln.get("qty")) * _num(ln.get("unitPrice"))) for ln in lines)
    )
    number = str(po.data.get("number") or "")
    sname = str(po.data.get("supplierName") or supplier.data.get("name") or "")
    payload = {
        "poId": ref_id,
        "number": number,
        "supplierId": po.data.get("supplierId"),
        "supplierName": sname,
        "lines": lines,
        "total": total,
        "note": po.data.get("note", ""),
    }
    return payload, f"PO {number} • {sname} • {_rp(total)}"


def _prepare_supplier(db: Session, s: SupplierData) -> tuple[str, dict, str]:
    name = s.name.strip()
    if not name:
        raise BadRequest("Nama supplier wajib diisi")
    suppliers = list(
        db.scalars(
            select(Doc).where(Doc.collection == "suppliers", Doc.deleted.is_(False))
        )
    )
    same_name = {
        d.id
        for d in suppliers
        if str(d.data.get("name") or "").strip().lower() == name.lower()
    }
    before = None
    if s.action == "create":
        if same_name:
            raise Conflict("Supplier dengan nama itu sudah ada")
        sid = new_id()
    else:
        current = next((d for d in suppliers if d.id == (s.supplier_id or "")), None)
        if current is None:
            raise NotFound("Supplier tidak ditemukan")
        if same_name - {current.id}:
            raise Conflict("Supplier lain dengan nama itu sudah ada")
        sid = current.id
        before = {k: current.data.get(k, "") for k in ("name", "phone", "note")}
    payload = {
        "action": s.action,
        "supplierId": sid,
        "name": name,
        "phone": s.phone.strip(),
        "note": s.note.strip(),
        "before": before,
    }
    return (
        sid,
        payload,
        f"Supplier {'baru' if s.action == 'create' else 'ubah'}: {name}",
    )


def _prepare_ingredient(db: Session, s: IngredientData) -> tuple[str, dict, str]:
    name, unit = s.name.strip(), s.unit.strip()
    if not name or not unit:
        raise BadRequest("Nama dan satuan bahan wajib diisi")
    items = list(
        db.scalars(
            select(Doc).where(Doc.collection == "ingredients", Doc.deleted.is_(False))
        )
    )
    same = {
        d.id
        for d in items
        if str(d.data.get("name") or "").strip().lower() == name.lower()
    }
    before = None
    if s.action == "create":
        if same:
            raise Conflict("Bahan dengan nama itu sudah ada")
        iid = new_id()
    else:
        current = next((d for d in items if d.id == (s.ingredient_id or "")), None)
        if current is None:
            raise NotFound("Bahan tidak ditemukan")
        if same - {current.id}:
            raise Conflict("Bahan lain dengan nama itu sudah ada")
        if unit != str(current.data.get("unit") or ""):
            raise BadRequest(
                "Satuan dasar tidak bisa diubah karena dipakai stok dan resep. Buat bahan baru bila perlu."
            )
        iid = current.id
        before = {
            k: current.data.get(k)
            for k in ("name", "unit", "minStock", "buyUnit", "buyFactor")
        }
    buy_unit = s.buy_unit.strip()
    payload = {
        "action": s.action,
        "ingredientId": iid,
        "name": name,
        "unit": unit,
        "minStock": s.min_stock,
        "buyUnit": buy_unit,
        "buyFactor": s.buy_factor if buy_unit else 1.0,
        "before": before,
    }
    return iid, payload, f"Bahan {'baru' if s.action == 'create' else 'ubah'}: {name}"


# ---------- efek pada dokumen PO / supplier (dilakukan server) ----------


def _set_po_state(
    db: Session,
    po_id: str,
    outlet: str,
    now: int,
    *,
    status: str,
    approval_id: str | None = None,
    note: str = "",
    extra: dict | None = None,
) -> None:
    po = db.get(Doc, ("purchase_orders", po_id))
    if po is None or po.deleted:
        raise Conflict("PO tidak ditemukan")
    data = {k: v for k, v in po.data.items() if k not in ("approvalId", "rejectNote")}
    data["status"] = status
    if approval_id:
        data["approvalId"] = approval_id
    if note:
        data["rejectNote"] = note
    data.update(extra or {})
    data["updatedAt"] = now
    sync_service.lock_counter(db)
    sync_service.upsert_doc(db, "purchase_orders", po_id, outlet, data, now)


def _apply_approved(db: Session, req: ApprovalRequest, now: int) -> None:
    if req.type == "purchase_order":
        po = db.get(Doc, ("purchase_orders", req.ref_id))
        if (
            po is None
            or po.deleted
            or po.data.get("status") != "pending"
            or po.data.get("approvalId") != req.id
        ):
            raise Conflict("PO sudah berubah. Minta pemohon mengajukan ulang.")
        _set_po_state(
            db,
            req.ref_id,
            req.outlet_id,
            now,
            status="ordered",
            approval_id=req.id,
            extra={"approvedAt": now},
        )
    elif req.type == "supplier":
        p = req.payload
        data = {
            "id": p["supplierId"],
            "name": p["name"],
            "phone": p.get("phone", ""),
            "note": p.get("note", ""),
            "updatedAt": now,
        }
        sync_service.lock_counter(db)
        sync_service.upsert_doc(db, "suppliers", p["supplierId"], None, data, now)
    elif req.type == "ingredient":
        p = req.payload
        data = {
            "id": p["ingredientId"],
            "name": p["name"],
            "unit": p["unit"],
            "minStock": p.get("minStock", 0),
            "buyUnit": p.get("buyUnit", ""),
            "buyFactor": p.get("buyFactor", 1.0),
            "updatedAt": now,
        }
        sync_service.lock_counter(db)
        sync_service.upsert_doc(db, "ingredients", p["ingredientId"], None, data, now)


def _apply_rejected(db: Session, req: ApprovalRequest, note: str, now: int) -> None:
    if req.type == "purchase_order":
        _set_po_state(
            db,
            req.ref_id,
            req.outlet_id,
            now,
            status="rejected",
            approval_id=req.id,
            note=note,
        )


# ---------- aksi ----------


def _label(req: ApprovalRequest) -> str:
    p = req.payload
    if req.type == "purchase_order":
        return f"PO {p.get('number', '')} • {p.get('supplierName', '')}".strip(" •")
    if req.type == "ingredient":
        return f"Bahan {'baru' if p.get('action') == 'create' else 'ubah'}: {p.get('name', '')}"
    return f"Supplier {'baru' if p.get('action') == 'create' else 'ubah'}: {p.get('name', '')}"


def _emit(db: Session, name: str, req: ApprovalRequest, **extra) -> None:
    events.emit(
        name,
        db=db,
        approval_id=req.id,
        type=req.type,
        outlet_id=req.outlet_id,
        requested_by=req.requested_by,
        label=_label(req),
        status=req.status,
        **extra,
    )


def create(db: Session, actor: User, data: ApprovalCreate) -> ApprovalRequest:
    if actor.role == Role.owner.value:
        raise Forbidden("Owner tidak perlu mengajukan persetujuan")
    if not can(actor, "approvals.create") or actor.outlet_id is None:
        raise Forbidden("Role Anda tidak dapat mengajukan persetujuan")

    if data.type == "purchase_order":
        ref_id = (data.ref_id or "").strip()
        payload, title = _prepare_po(db, actor, ref_id)
    elif data.type == "supplier":
        if data.supplier is None:
            raise BadRequest("Data supplier wajib diisi")
        ref_id, payload, title = _prepare_supplier(db, data.supplier)
    else:
        if data.ingredient is None:
            raise BadRequest("Data bahan wajib diisi")
        ref_id, payload, title = _prepare_ingredient(db, data.ingredient)

    dup = db.scalar(
        select(ApprovalRequest.id)
        .where(
            ApprovalRequest.type == data.type,
            ApprovalRequest.ref_id == ref_id,
            ApprovalRequest.status.in_(PENDING),
        )
        .limit(1)
    )
    if dup:
        raise Conflict("Sudah ada pengajuan yang menunggu untuk data ini")

    now = _now()
    # pemohon yang sendiri berwenang tingkat 1 langsung ke tahap akhir
    stage = "pending_owner" if _l1(actor) else "pending_l1"
    req = ApprovalRequest(
        id=new_id(),
        type=data.type,
        outlet_id=actor.outlet_id,
        requested_by=actor.id,
        ref_id=ref_id,
        title=title,
        payload=payload,
        status=stage,
        l1_note="",
        owner_note="",
        created_at=now,
        updated_at=now,
    )
    db.add(req)
    if data.type == "purchase_order":
        _set_po_state(
            db, ref_id, actor.outlet_id, now, status="pending", approval_id=req.id
        )
    db.commit()
    db.refresh(req)
    _emit(db, "approval.submitted", req, stage=stage)
    return req


def approve(db: Session, actor: User, approval_id: str, note: str) -> ApprovalRequest:
    req = get_for(db, actor, approval_id, lock=True)
    if req.status in DECIDED:
        raise Conflict("Pengajuan sudah diputuskan")
    if not can_approve(actor, req):
        raise Forbidden("Anda tidak berwenang menyetujui pengajuan ini pada tahap ini")
    now = _now()
    if req.status == "pending_l1":
        req.l1_by, req.l1_at, req.l1_note = actor.id, now, note
        req.status = "pending_owner"
        event = "approval.advanced"
    else:
        req.owner_by, req.owner_at, req.owner_note = actor.id, now, note
        req.status = "approved"
        _apply_approved(db, req, now)
        event = "approval.decided"
    req.updated_at = now
    db.commit()
    db.refresh(req)
    _emit(db, event, req, actor_id=actor.id)
    return req


def reject(db: Session, actor: User, approval_id: str, note: str) -> ApprovalRequest:
    req = get_for(db, actor, approval_id, lock=True)
    if req.status in DECIDED:
        raise Conflict("Pengajuan sudah diputuskan")
    if not can_reject(actor, req):
        raise Forbidden("Anda tidak berwenang menolak pengajuan ini pada tahap ini")
    now = _now()
    if _final(actor):
        req.owner_by, req.owner_at, req.owner_note = actor.id, now, note
    else:
        req.l1_by, req.l1_at, req.l1_note = actor.id, now, note
    req.status = "rejected"
    req.updated_at = now
    _apply_rejected(db, req, note, now)
    db.commit()
    db.refresh(req)
    _emit(db, "approval.decided", req, actor_id=actor.id, note=note)
    return req


def withdraw(db: Session, actor: User, approval_id: str) -> ApprovalRequest:
    req = get_for(db, actor, approval_id, lock=True)
    if req.status in DECIDED:
        raise Conflict("Pengajuan sudah diputuskan")
    if not can_withdraw(actor, req):
        raise Forbidden("Hanya pemohon yang dapat menarik pengajuan")
    now = _now()
    req.status = "withdrawn"
    req.updated_at = now
    if req.type == "purchase_order":
        _set_po_state(
            db, req.ref_id, req.outlet_id, now, status="draft"
        )  # bisa diedit lagi
    db.commit()
    db.refresh(req)
    _emit(db, "approval.withdrawn", req)
    return req


# ---------- daftar, hitungan, dan bentuk keluaran ----------


def _inbox_stmt(actor: User):
    if _final(actor):
        return select(ApprovalRequest).where(ApprovalRequest.status == "pending_owner")
    if _l1(actor):
        return select(ApprovalRequest).where(
            ApprovalRequest.status == "pending_l1",
            ApprovalRequest.outlet_id == actor.outlet_id,
            ApprovalRequest.requested_by != actor.id,
        )
    return None


def list_for(
    db: Session, actor: User, scope: str, limit: int, offset: int
) -> list[ApprovalRequest]:
    if scope == "mine":
        stmt = select(ApprovalRequest).where(ApprovalRequest.requested_by == actor.id)
    elif scope == "inbox":
        stmt = _inbox_stmt(actor)
        if stmt is None:
            return []
    elif (
        scope == "pending"
    ):  # semua yang masih menunggu (owner: semua outlet; penyetuju: outlet sendiri)
        stmt = select(ApprovalRequest).where(ApprovalRequest.status.in_(PENDING))
        if _final(actor):
            pass
        elif _l1(actor):
            stmt = stmt.where(ApprovalRequest.outlet_id == actor.outlet_id)
        else:
            return []
    else:  # history
        stmt = select(ApprovalRequest).where(ApprovalRequest.status.in_(DECIDED))
        if _final(actor):
            pass
        elif _l1(actor):
            stmt = stmt.where(ApprovalRequest.outlet_id == actor.outlet_id)
        else:
            return []
    stmt = stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def counts(db: Session, actor: User) -> ApprovalCounts:
    stmt = _inbox_stmt(actor)
    inbox = (
        db.scalar(select(func.count()).select_from(stmt.subquery()))
        if stmt is not None
        else 0
    )
    mine_open = db.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(
            ApprovalRequest.requested_by == actor.id,
            ApprovalRequest.status.in_(PENDING),
        )
    )
    return ApprovalCounts(inbox=inbox or 0, mine_open=mine_open or 0)


def to_out(db: Session, actor: User, reqs: list[ApprovalRequest]) -> list[ApprovalOut]:
    user_ids = {u for r in reqs for u in (r.requested_by, r.l1_by, r.owner_by) if u}
    users = (
        {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    outlet_ids = {r.outlet_id for r in reqs}
    outlets = (
        {
            o.id: o.name
            for o in db.scalars(select(Outlet).where(Outlet.id.in_(outlet_ids)))
        }
        if outlet_ids
        else {}
    )
    return [
        ApprovalOut(
            id=r.id,
            type=r.type,
            outlet_id=r.outlet_id,
            outlet_name=outlets.get(r.outlet_id, ""),
            requested_by=r.requested_by,
            requested_by_name=users.get(r.requested_by, ""),
            title=r.title,
            payload=r.payload,
            status=r.status,
            l1_by_name=users.get(r.l1_by) if r.l1_by else None,
            l1_at=r.l1_at,
            l1_note=r.l1_note or "",
            owner_by_name=users.get(r.owner_by) if r.owner_by else None,
            owner_at=r.owner_at,
            owner_note=r.owner_note or "",
            created_at=r.created_at,
            updated_at=r.updated_at,
            can_approve=can_approve(actor, r),
            can_reject=can_reject(actor, r),
            can_withdraw=can_withdraw(actor, r),
        )
        for r in reqs
    ]
