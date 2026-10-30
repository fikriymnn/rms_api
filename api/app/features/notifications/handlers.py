import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import events
from app.core.utils import new_id
from app.features.outlets.models import Outlet
from app.features.users.models import User
from app.features.roles import service as roles_service

from . import push
from .models import DeviceToken, Notification

log = logging.getLogger("rms.notify")


def _holders(db: Session, perm: str) -> tuple[str, ...]:
    """Penerima ditentukan oleh izin (bukan nama role) agar ikut master role."""
    return roles_service.role_keys_with(db, perm)


@dataclass
class Notice:
    users: list[User]
    type: str  # approval | proposal | order
    ref_id: str
    title: str
    body: str
    channel: str  # approvals | kitchen_orders
    outlet_id: str | None = None


def _users(
    db: Session,
    roles: tuple[str, ...],
    *,
    outlet_id: str | None = None,
    exclude: set[str] = frozenset(),
) -> list[User]:  # type: ignore[assignment]
    stmt = select(User).where(User.active.is_(True), User.role.in_(list(roles)))
    if outlet_id is not None:
        stmt = stmt.where(User.outlet_id == outlet_id)
    return [u for u in db.scalars(stmt) if u.id not in exclude]


def _one(db: Session, user_id: str | None) -> list[User]:
    u = db.get(User, user_id) if user_id else None
    return [u] if u is not None and u.active else []


def _q(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# ---------- persetujuan ----------


def _approval_submitted(db: Session, p: dict) -> list[Notice]:
    requester, outlet = db.get(User, p["requested_by"]), db.get(Outlet, p["outlet_id"])
    who = f"{requester.name if requester else '-'} ({outlet.name if outlet else '-'})"
    if p["stage"] == "pending_l1":
        users = _users(
            db,
            _holders(db, "approvals.approve_l1"),
            outlet_id=p["outlet_id"],
            exclude={p["requested_by"]},
        )
    else:
        users = _users(db, _holders(db, "approvals.approve_final"))
    return [
        Notice(
            users,
            "approval",
            p["approval_id"],
            "Pengajuan menunggu persetujuan",
            f"{p['label']} • dari {who}",
            "approvals",
            p["outlet_id"],
        )
    ]


def _approval_advanced(db: Session, p: dict) -> list[Notice]:
    approver = db.get(User, p.get("actor_id"))
    by = approver.name if approver else "tingkat 1"
    common = (p["approval_id"],)
    return [
        Notice(
            _users(db, _holders(db, "approvals.approve_final")),
            "approval",
            *common,
            "Menunggu persetujuan Anda",
            f"{p['label']} • disetujui {by}",
            "approvals",
            p["outlet_id"],
        ),
        Notice(
            _one(db, p["requested_by"]),
            "approval",
            *common,
            "Pengajuan lolos tingkat 1",
            f"{p['label']} • menunggu owner",
            "approvals",
            p["outlet_id"],
        ),
    ]


def _approval_decided(db: Session, p: dict) -> list[Notice]:
    approved = p["status"] == "approved"
    body = p["label"] + ("" if approved or not p.get("note") else f" • {p['note']}")
    return [
        Notice(
            _one(db, p["requested_by"]),
            "approval",
            p["approval_id"],
            "Pengajuan disetujui" if approved else "Pengajuan ditolak",
            body[:250],
            "approvals",
            p["outlet_id"],
        )
    ]


# ---------- usulan menu ----------


def _proposal_submitted(db: Session, p: dict) -> list[Notice]:
    return [
        Notice(
            _users(db, _holders(db, "proposals.decide")),
            "proposal",
            p["proposal_id"],
            "Usulan menu baru",
            f"{p['name']} • dari {p['by_name']}"[:250],
            "approvals",
        )
    ]


def _proposal_decided(db: Session, p: dict) -> list[Notice]:
    approved = p["status"] == "approved"
    body = p["name"] + ("" if approved or not p.get("note") else f" • {p['note']}")
    return [
        Notice(
            _one(db, p.get("requested_by")),
            "proposal",
            p["proposal_id"],
            "Usulan menu disetujui" if approved else "Usulan menu ditolak",
            body[:250],
            "approvals",
        )
    ]


# ---------- pesanan dapur ----------


def _order_items_added(db: Session, p: dict) -> list[Notice]:
    items = p["items"]  # [[nama, jumlah], ...]
    shown = ", ".join(f"{_q(q)}× {n}" for n, q in items[:3])
    if len(items) > 3:
        shown += f" dan {len(items) - 3} lainnya"
    title = f"{'Pesanan baru' if p['is_new'] else 'Tambahan pesanan'} • {p['where']}"
    return [
        Notice(
            _users(db, _holders(db, "kitchen.notify"), outlet_id=p["outlet_id"]),
            "order",
            p["order_id"],
            title,
            shown[:250],
            "kitchen_orders",
            p["outlet_id"],
        )
    ]


_BUILDERS = {
    "approval.submitted": _approval_submitted,
    "approval.advanced": _approval_advanced,
    "approval.decided": _approval_decided,
    "proposal.submitted": _proposal_submitted,
    "proposal.decided": _proposal_decided,
    "order.items_added": _order_items_added,
}


def _deliver(db: Session, notices: list[Notice]) -> None:
    now = int(time.time() * 1000)
    rows: list[tuple[Notification, User, Notice]] = []
    for n in notices:
        for u in n.users:
            row = Notification(
                id=new_id(),
                user_id=u.id,
                outlet_id=n.outlet_id,
                type=n.type,
                title=n.title,
                body=n.body,
                data={"type": n.type, "id": n.ref_id},
                created_at=now,
            )
            db.add(row)
            rows.append((row, u, n))
    if not rows:
        return
    db.commit()
    tokens: dict[str, list[str]] = defaultdict(list)
    for t in db.scalars(
        select(DeviceToken).where(DeviceToken.user_id.in_({u.id for _, u, _ in rows}))
    ):
        tokens[t.user_id].append(t.token)
    push.dispatch(
        [
            {
                "token": tok,
                "title": n.title,
                "body": n.body,
                "channel": n.channel,
                "data": {"type": n.type, "id": n.ref_id, "nid": row.id},
            }
            for row, u, n in rows
            for tok in tokens.get(u.id, [])
        ]
    )


@events.on_event
def _on_event(name: str, payload: dict) -> None:
    builder, db = _BUILDERS.get(name), payload.get("db")
    if builder is None or db is None:
        return
    try:
        _deliver(db, [n for n in builder(db, payload) if n.users])
    except Exception:
        db.rollback()
        log.exception("notifikasi gagal untuk %s", name)
