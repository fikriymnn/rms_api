import json
import re
import time
import uuid

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Forbidden
from app.features.outlets import service as outlet_service
from app.features.users.models import User
from app.features.users.roles import Role

from .models import Doc
from app.features.roles.service import has_any
from .policy import REGISTRY, any_write, op_perms
from .schemas import PullResponse, PushResult, SyncDocIn, SyncDocOut
from app.core import events

MAX_DOC_BYTES = 64 * 1024
MAX_FUTURE_MS = 24 * 3600 * 1000
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def resolve_outlet(db: Session, actor: User, requested: str | None) -> str | None:
    """Outlet aktif. Non-owner SELALU outletnya sendiri; owner memilih sendiri."""
    if actor.role == Role.owner.value:
        if requested is None:
            return None
        if outlet_service.get_outlet(db, requested) is None:
            raise BadRequest("Outlet tidak ditemukan")
        return requested
    if requested not in (None, actor.outlet_id):
        raise Forbidden("Anda hanya boleh mengakses outlet Anda sendiri")
    return actor.outlet_id


def readable_collections(actor: User) -> list[str]:
    return [c for c, s in REGISTRY.items() if has_any(actor, s.read)]


def writable_collections(actor: User) -> list[str]:
    return [c for c, s in REGISTRY.items() if has_any(actor, any_write(s))]


def _visible(actor: User, doc: Doc) -> bool:
    spec = REGISTRY.get(doc.collection)
    if spec is None or not has_any(actor, spec.read):
        return False
    return spec.read_filter is None or spec.read_filter(actor, doc.data)


def pull(
    db: Session, actor: User, outlet_id: str | None, since: int, limit: int
) -> PullResponse:
    outlet = resolve_outlet(db, actor, outlet_id)
    stmt = select(Doc).where(
        Doc.seq > since, Doc.collection.in_(readable_collections(actor))
    )
    if outlet is None:
        stmt = stmt.where(Doc.outlet_id.is_(None))
    else:
        stmt = stmt.where(or_(Doc.outlet_id.is_(None), Doc.outlet_id == outlet))
    rows = list(db.scalars(stmt.order_by(Doc.seq).limit(limit + 1)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    # kursor maju mengikuti baris mentah, walau sebagian disaring oleh read_filter
    next_since = rows[-1].seq if rows else since
    return PullResponse(
        docs=[SyncDocOut.model_validate(d) for d in rows if _visible(actor, d)],
        next_since=next_since,
        has_more=has_more,
    )


def _next_seq(db: Session) -> int:
    db.execute(text("UPDATE counters SET v = LAST_INSERT_ID(v + 1) WHERE name = 'seq'"))
    return int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())


def _write_doc(
    db: Session,
    existing: Doc | None,
    collection: str,
    doc_id: str,
    outlet: str | None,
    data: dict,
    updated_at: int,
    deleted: bool,
) -> int:
    seq = _next_seq(db)
    if existing is None:
        db.add(
            Doc(
                collection=collection,
                id=doc_id,
                outlet_id=outlet,
                data=data,
                updated_at=updated_at,
                deleted=deleted,
                seq=seq,
            )
        )
    else:
        existing.data = data
        existing.updated_at = updated_at
        existing.deleted = deleted
        existing.seq = seq
    db.flush()  # agar dokumen kembar dalam satu batch terdeteksi
    return seq


def lock_counter(db: Session) -> None:
    """Kunci penghitung seq. Menulis dokumen di luar push() wajib memanggil ini dulu."""
    db.execute(text("SELECT v FROM counters WHERE name = 'seq' FOR UPDATE"))


def upsert_doc(
    db: Session,
    collection: str,
    doc_id: str,
    outlet: str | None,
    data: dict,
    now_ms: int,
    deleted: bool = False,
) -> int:
    existing = db.get(Doc, (collection, doc_id))
    return _write_doc(db, existing, collection, doc_id, outlet, data, now_ms, deleted)


# ---------- efek samping yang dikerjakan server (tidak bisa dipalsukan klien) ----------


def _num(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _record_recipe_history(
    db: Session,
    by_id: str,
    by_name: str,
    recipe_id: str,
    old: dict | None,
    new: dict,
    now_ms: int,
    via: str = "",
) -> None:
    before, after = (old or {}).get("lines"), new.get("lines")
    if old is not None and before == after:
        return  # hanya takaran yang dicatat
    hid = f"rev_{recipe_id}_{uuid.uuid4().hex[:12]}"
    data = {
        "id": hid,
        "recipeId": recipe_id,
        "at": now_ms,
        "by": by_id,
        "byName": by_name,
        "before": before,
        "after": after,
        "via": via,
    }
    _write_doc(db, None, "recipe_history", hid, None, data, now_ms, False)


def _deduct_stock(
    db: Session,
    actor: User,
    outlet: str | None,
    order_id: str,
    order: dict,
    now_ms: int,
) -> None:
    """Potong stok dari resep saat order dibayar. Idempoten lewat id mutasi."""
    items = [i for i in (order.get("items") or []) if isinstance(i, dict)]
    menu_ids = {str(i["menuItemId"]) for i in items if i.get("menuItemId")}
    if not menu_ids:
        return
    recipes = {
        d.id: d.data
        for d in db.scalars(
            select(Doc).where(
                Doc.collection == "recipes",
                Doc.id.in_(menu_ids),
                Doc.deleted.is_(False),
            )
        )
    }
    used: dict[str, float] = {}
    for it in items:
        recipe = recipes.get(str(it.get("menuItemId")))
        if not recipe:
            continue
        portions = _num(it.get("qty"))
        for line in recipe.get("lines") or []:
            ing = line.get("ingredientId") if isinstance(line, dict) else None
            if ing:
                used[str(ing)] = (
                    used.get(str(ing), 0.0) + _num(line.get("qty")) * portions
                )
    paid_at = int(_num(order.get("paidAt")) or now_ms)
    for ing, qty in used.items():
        if qty <= 0:
            continue
        move_id = f"sale_{order_id}_{ing}"
        if db.get(Doc, ("stock_moves", move_id)) is not None:
            continue
        data = {
            "id": move_id,
            "ingredientId": ing,
            "type": "sale",
            "qty": -qty,
            "at": paid_at,
            "unitCost": None,
            "orderId": order_id,
            "note": str(order.get("number") or ""),
            "userName": actor.name,
        }
        _write_doc(db, None, "stock_moves", move_id, outlet, data, now_ms, False)


def _create_purchase_moves(
    db: Session, actor: User, outlet: str | None, gr_id: str, gr: dict, now_ms: int
) -> None:
    """Penerimaan barang tercatat -> server membuat mutasi stok masuk (dengan harga beli)."""
    at = int(_num(gr.get("at")) or now_ms)
    for ln in gr.get("lines") or []:
        if not isinstance(ln, dict) or not ln.get("ingredientId"):
            continue
        qty = _num(ln.get("qty"))
        factor = _num(ln.get("factor")) or 1.0
        if qty <= 0:
            continue
        ing = str(ln["ingredientId"])
        move_id = f"rcv_{gr_id}_{ing}"
        if db.get(Doc, ("stock_moves", move_id)) is not None:
            continue
        data = {
            "id": move_id,
            "ingredientId": ing,
            "type": "purchase",
            "qty": qty * factor,
            "at": at,
            "unitCost": _num(ln.get("unitPrice")) / factor,
            "orderId": "",
            "note": f"{gr.get('number', '')} • {gr.get('supplierName', '')}",
            "userName": actor.name,
        }
        _write_doc(db, None, "stock_moves", move_id, outlet, data, now_ms, False)


def _publish_proposal(
    db: Session, actor: User, proposal_id: str, p: dict, now_ms: int
) -> None:
    """Usulan disetujui owner: terbitkan menu (dan resep) di semua outlet, satu transaksi."""
    final_price = int(_num(p.get("finalPrice")))
    if final_price <= 0:
        return
    is_change = p.get("kind") == "change"
    item_id = str(p.get("targetId")) if is_change else proposal_id
    existing = db.get(Doc, ("menu_items", item_id))
    if is_change and (existing is None or existing.deleted):
        return  # menu yang dituju sudah tidak ada: tidak ada yang diterbitkan
    base = dict(existing.data) if existing is not None else {}
    item = {
        **base,
        "id": item_id,
        "name": p.get("name") or base.get("name", ""),
        "category": p.get("category") or base.get("category", ""),
        "description": (
            p["description"]
            if p.get("description") is not None
            else base.get("description", "")
        ),
        "price": final_price,
        "available": base.get("available", True),
        "updatedAt": now_ms,
    }
    _write_doc(db, existing, "menu_items", item_id, None, item, now_ms, False)

    recipe = p.get("recipe")
    if isinstance(recipe, list):
        lines = [
            {"ingredientId": str(ln["ingredientId"]), "qty": _num(ln.get("qty"))}
            for ln in recipe
            if isinstance(ln, dict)
            and ln.get("ingredientId")
            and _num(ln.get("qty")) > 0
        ]
        old_recipe = db.get(Doc, ("recipes", item_id))
        new_data = {"id": item_id, "lines": lines}
        _write_doc(db, old_recipe, "recipes", item_id, None, new_data, now_ms, False)
        _record_recipe_history(
            db,
            str(p.get("submittedBy") or actor.id),
            str(p.get("submittedByName") or ""),
            item_id,
            old_recipe.data if old_recipe is not None else None,
            new_data,
            now_ms,
            via=f"usulan menu (disetujui {actor.name})",
        )


def _after_write(
    db: Session,
    actor: User,
    it: SyncDocIn,
    old: dict | None,
    target: str | None,
    now_ms: int,
) -> None:
    prev = (old or {}).get("status")
    status = it.data.get("status")
    if it.collection == "recipes":
        _record_recipe_history(db, actor.id, actor.name, it.id, old, it.data, now_ms)
    elif it.collection == "orders":
        if status == "paid" and prev not in ("paid", "refunded"):
            _deduct_stock(db, actor, target, it.id, it.data, now_ms)
        _queue_order_event(db, target, it.id, old, it.data)
    elif it.collection == "menu_proposals":
        name = str(it.data.get("name") or "")
        if status == "approved" and prev != "approved":
            _publish_proposal(db, actor, it.id, it.data, now_ms)
        if old is None and status == "pending":
            _queue_event(
                db,
                "proposal.submitted",
                proposal_id=it.id,
                name=name,
                by_name=actor.name,
            )
        elif prev == "pending" and status in ("approved", "rejected"):
            _queue_event(
                db,
                "proposal.decided",
                proposal_id=it.id,
                name=name,
                status=status,
                requested_by=it.data.get("submittedBy"),
                note=str(it.data.get("decisionNote") or ""),
            )
    elif it.collection == "goods_receipts":
        _create_purchase_moves(db, actor, target, it.id, it.data, now_ms)


# ---------- push ----------


def _rejected(it: SyncDocIn, reason: str) -> PushResult:
    return PushResult(
        collection=it.collection, id=it.id, status="rejected", reason=reason
    )


def _push_one(
    db: Session, actor: User, outlet: str | None, it: SyncDocIn, now_ms: int
) -> PushResult:
    spec = REGISTRY.get(it.collection)
    if spec is None:
        return _rejected(it, "unknown_collection")
    # pemeriksaan kasar: punya izin menulis apa pun di koleksi ini?
    if not has_any(actor, any_write(spec)):
        return _rejected(it, "forbidden")
    if not _ID_RE.match(it.id):
        return _rejected(it, "bad_id")
    if it.updated_at <= 0 or it.updated_at > now_ms + MAX_FUTURE_MS:
        return _rejected(it, "bad_timestamp")
    if len(json.dumps(it.data, separators=(",", ":")).encode()) > MAX_DOC_BYTES:
        return _rejected(it, "too_large")

    target = None if spec.scope == "shared" else outlet
    if spec.scope == "outlet" and target is None:
        return _rejected(it, "outlet_required")

    existing = db.get(Doc, (it.collection, it.id))
    if existing is not None and existing.outlet_id != target:
        return _rejected(it, "id_conflict")  # jangan menimpa dokumen outlet lain
    # izin per operasi: tambah / ubah / hapus
    if not has_any(actor, op_perms(spec, is_new=existing is None, deleting=it.deleted)):
        return _rejected(it, "forbidden")

    if spec.append_only:
        if existing is not None:
            if existing.data == it.data and not it.deleted:  # kirim ulang yang identik
                return PushResult(
                    collection=it.collection, id=it.id, status="ok", seq=existing.seq
                )
            return _rejected(it, "append_only")
        if it.deleted:
            return _rejected(it, "append_only")
    elif existing is not None and existing.updated_at >= it.updated_at:
        return PushResult(
            collection=it.collection, id=it.id, status="stale", seq=existing.seq
        )

    old = existing.data if existing is not None else None
    if spec.check is not None:
        error = spec.check(actor, it.data, old)
        if error:
            return _rejected(it, error)

    if spec.precheck is not None:
        error = spec.precheck(db, actor, it.id, it.data, old, target)
        if error:
            return _rejected(it, error)

    seq = _write_doc(
        db, existing, it.collection, it.id, target, it.data, it.updated_at, it.deleted
    )
    if not it.deleted:
        _after_write(db, actor, it, old, target, now_ms)
    return PushResult(collection=it.collection, id=it.id, status="ok", seq=seq)


def push(
    db: Session, actor: User, outlet_id: str | None, items: list[SyncDocIn]
) -> list[PushResult]:
    outlet = resolve_outlet(db, actor, outlet_id)
    # kunci penghitung dulu: semua push berjalan berurutan, jadi urutan seq = urutan commit
    db.execute(text("SELECT v FROM counters WHERE name = 'seq' FOR UPDATE"))
    now_ms = int(time.time() * 1000)
    results = [_push_one(db, actor, outlet, it, now_ms) for it in items]
    db.commit()
    for name, payload in db.info.pop("events", []):
        events.emit(name, db=db, **payload)
    return results


def _queue_event(db: Session, event: str, /, **payload) -> None:
    """Kejadian dikirim SESUDAH commit (lihat push)."""
    db.info.setdefault("events", []).append((event, payload))


def _item_key(it: dict) -> str:
    return str(it.get("id") or f"{it.get('menuItemId')}|{it.get('note', '')}")


def _queue_order_event(
    db: Session, outlet: str | None, order_id: str, old: dict | None, new: dict
) -> None:
    if new.get("status") not in (
        "open",
        "paid",
    ):  # bayar langsung tetap memberi tahu dapur
        return
    old_qty = {
        _item_key(i): _num(i.get("qty"))
        for i in ((old or {}).get("items") or [])
        if isinstance(i, dict)
    }
    added = []
    for it in new.get("items") or []:
        if not isinstance(it, dict):
            continue
        delta = _num(it.get("qty")) - old_qty.get(_item_key(it), 0.0)
        if delta > 0:
            added.append([str(it.get("name") or "Item"), delta])
    if not added:
        return
    if new.get("type") == "takeaway":
        where = "Takeaway"
    else:
        table = (
            db.get(Doc, ("tables", str(new["tableId"]))) if new.get("tableId") else None
        )
        label = (
            str(table.data.get("name") or table.data.get("number") or "")
            if table is not None
            else ""
        )
        where = (
            (label if label.lower().startswith("meja") else f"Meja {label}")
            if label
            else "Dine-in"
        )
    _queue_event(
        db,
        "order.items_added",
        outlet_id=outlet,
        order_id=order_id,
        is_new=old is None,
        where=where,
        items=added,
    )
