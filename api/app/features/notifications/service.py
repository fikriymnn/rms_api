import time

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.utils import new_id
from app.features.users.models import User

from .models import DeviceToken, Notification


def _now() -> int:
    return int(time.time() * 1000)


def register_device(db: Session, user: User, token: str, platform: str) -> None:
    """Satu token hanya milik satu akun: bila perangkat dipakai akun lain, kepemilikan berpindah."""
    now = _now()
    row = db.scalar(select(DeviceToken).where(DeviceToken.token == token))
    if row is None:
        db.add(
            DeviceToken(
                id=new_id(),
                user_id=user.id,
                token=token,
                platform=platform,
                created_at=now,
                last_seen_at=now,
            )
        )
    else:
        row.user_id, row.platform, row.last_seen_at = user.id, platform, now
    db.commit()


def unregister_device(db: Session, user: User, token: str) -> None:
    db.execute(
        delete(DeviceToken).where(
            DeviceToken.token == token, DeviceToken.user_id == user.id
        )
    )
    db.commit()


def drop_user_tokens(db: Session, user_id: str) -> None:
    """Dipanggil saat akses dicabut. Tidak commit: pemanggil yang commit."""
    db.execute(delete(DeviceToken).where(DeviceToken.user_id == user_id))


def list_for(
    db: Session, user: User, limit: int, before: int | None
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if before is not None:
        stmt = stmt.where(Notification.created_at < before)
    return list(
        db.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit)).all()
    )


def unread_count(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
        or 0
    )


def mark_read(
    db: Session,
    user: User,
    ids: list[str],
    all_: bool,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> None:
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )  # hanya milik sendiri
        .values(read_at=_now())
    )
    if all_:
        pass
    elif ref_type:
        stmt = stmt.where(Notification.type == ref_type)
        if ref_id:
            stmt = stmt.where(Notification.data["id"].as_string() == ref_id)
    elif ids:
        stmt = stmt.where(Notification.id.in_(ids))
    else:
        return
    db.execute(stmt)
    db.commit()
