"""Absensi kiosk: satu perangkat bersama, karyawan memilih namanya lalu memasukkan PIN."""

from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BadRequest, Forbidden, NotFound, TooManyRequests
from app.core.security import hash_password, verify_password
from app.features.roles.service import can
from app.features.users.models import User

from . import service
from .schemas import ConsentOut, KioskStaffOut

MAX_FAILS = 5
LOCK_MS = 5 * 60 * 1000
TICKET_HOURS = 12  # cukup untuk antrean offline selama satu shift


def _outlet_of(kiosk: User) -> str:
    if kiosk.outlet_id is None:
        raise Forbidden("Akun kiosk harus terikat satu outlet")
    return kiosk.outlet_id


def eligible(db: Session, kiosk: User, user_id: str) -> User:
    """Karyawan outlet kiosk yang aktif dan boleh absen (bukan akun kiosk)."""
    u = db.get(User, user_id)
    if (
        u is None
        or not u.active
        or u.outlet_id != _outlet_of(kiosk)
        or can(u, "attendance.kiosk")
        or not can(u, "attendance.clock")
    ):
        raise NotFound("Karyawan tidak ditemukan di outlet ini")
    return u


def staff(db: Session, kiosk: User) -> list[KioskStaffOut]:
    outlet = _outlet_of(kiosk)
    now = service.now_ms()
    rows = db.scalars(
        select(User)
        .where(User.outlet_id == outlet, User.active.is_(True))
        .order_by(User.name)
    ).all()
    out = []
    for u in rows:
        if can(u, "attendance.kiosk") or not can(u, "attendance.clock"):
            continue
        out.append(
            KioskStaffOut(
                id=u.id,
                name=u.name,
                position=u.position,
                role_name=u.role_name,
                has_pin=u.attendance_pin_set,
                consent_ok=u.attendance_consent_version
                == settings.attendance_consent_version,
                clocked_in=service._open_record(db, u.id, now) is not None,
            )
        )
    return out


def _issue(kiosk_id: str, user_id: str, event_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TICKET_HOURS)
    return jwt.encode(
        {"typ": "kiosk", "sub": user_id, "kid": kiosk_id, "eid": event_id, "exp": exp},
        settings.jwt_secret,
        algorithm="HS256",
    )


def check_ticket(
    ticket: str, kiosk: User, user_id: str, event_id: str | None = None
) -> None:
    try:
        p = jwt.decode(ticket, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise Forbidden("Sesi PIN kedaluwarsa. Masukkan PIN lagi")
    if (
        p.get("typ") != "kiosk"
        or p.get("sub") != user_id
        or p.get("kid") != kiosk.id
        or (event_id is not None and p.get("eid") != event_id)
    ):
        raise Forbidden("Sesi PIN tidak sah")


def verify_pin(db: Session, kiosk: User, user_id: str, pin: str, event_id: str) -> str:
    u = eligible(db, kiosk, user_id)
    db.refresh(u, with_for_update=True)  # percobaan serentak tidak melewati batas
    now = service.now_ms()
    if u.attendance_pin_locked_until and u.attendance_pin_locked_until > now:
        mins = max(1, -(-(u.attendance_pin_locked_until - now) // 60000))
        raise TooManyRequests(f"Terlalu banyak percobaan. Coba lagi {mins} menit lagi")
    if not u.attendance_pin_hash:
        raise Forbidden("PIN absensi belum diatur. Minta manager mengaturnya")
    if not verify_password(u.attendance_pin_hash, pin):
        u.attendance_pin_failed += 1
        left = MAX_FAILS - u.attendance_pin_failed
        if left <= 0:
            u.attendance_pin_failed = 0
            u.attendance_pin_locked_until = now + LOCK_MS
        db.commit()
        if left <= 0:
            raise TooManyRequests("PIN salah 5 kali. Dikunci 5 menit")
        raise Forbidden(f"PIN salah (sisa percobaan {left})")
    u.attendance_pin_failed = 0
    u.attendance_pin_locked_until = None
    db.commit()
    return _issue(kiosk.id, u.id, event_id)


def give_consent(
    db: Session, kiosk: User, user_id: str, ticket: str, version: int
) -> ConsentOut:
    u = eligible(db, kiosk, user_id)
    check_ticket(ticket, kiosk, u.id)
    return service.give_consent(db, u, version, by=kiosk.id)


def set_pin(db: Session, actor: User, user_id: str, pin: str) -> None:
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("Pengguna tidak ditemukan")
    if actor.outlet_id is not None and u.outlet_id != actor.outlet_id:
        raise Forbidden("Hanya untuk karyawan outlet Anda")
    u.attendance_pin_hash = hash_password(pin)
    u.attendance_pin_failed = 0
    u.attendance_pin_locked_until = None
    db.commit()


def clear_pin(db: Session, actor: User, user_id: str) -> None:
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("Pengguna tidak ditemukan")
    if actor.outlet_id is not None and u.outlet_id != actor.outlet_id:
        raise Forbidden("Hanya untuk karyawan outlet Anda")
    u.attendance_pin_hash = None
    u.attendance_pin_failed = 0
    u.attendance_pin_locked_until = None
    db.commit()


def set_my_pin(db: Session, actor: User, password: str, pin: str) -> None:
    if not verify_password(actor.password_hash, password):
        raise Forbidden("Password salah")
    actor.attendance_pin_hash = hash_password(pin)
    actor.attendance_pin_failed = 0
    actor.attendance_pin_locked_until = None
    db.commit()
