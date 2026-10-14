import json
import re
import time

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Forbidden
from app.features.outlets import service as outlet_service
from app.features.users.models import User
from app.features.users.roles import Role

from .models import Doc
from .policy import REGISTRY
from .schemas import PullResponse, PushResult, SyncDocIn, SyncDocOut

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
    return [c for c, s in REGISTRY.items() if actor.role in s.read]


def writable_collections(actor: User) -> list[str]:
    return [c for c, s in REGISTRY.items() if actor.role in s.write]


def _visible(actor: User, doc: Doc) -> bool:
    spec = REGISTRY.get(doc.collection)
    if spec is None or actor.role not in spec.read:
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
    if actor.role not in spec.write:
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

    if spec.check is not None:
        error = spec.check(actor, it.data, existing.data if existing else None)
        if error:
            return _rejected(it, error)

    seq = _next_seq(db)
    if existing is None:
        db.add(
            Doc(
                collection=it.collection,
                id=it.id,
                outlet_id=target,
                data=it.data,
                updated_at=it.updated_at,
                deleted=it.deleted,
                seq=seq,
            )
        )
    else:
        existing.data = it.data
        existing.updated_at = it.updated_at
        existing.deleted = it.deleted
        existing.seq = seq
    db.flush()  # agar dokumen kembar dalam satu batch terdeteksi
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
    return results
