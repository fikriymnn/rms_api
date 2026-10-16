import time

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.features.outlets import service as outlet_service
from app.features.users.models import User
from app.features.users.roles import Role

from . import photos
from .geo import distance_m
from .models import Attendance
from .schemas import AttendanceOut, MeOut, SummaryRow

STALE_MS = 16 * 3600 * 1000
MAX_FUTURE_MS = 2 * 60 * 1000
MAX_PAST_MS = 24 * 3600 * 1000
LATE_SYNC_MS = 5 * 60 * 1000


def now_ms() -> int:
    return int(time.time() * 1000)


def _flags(s: str) -> list[str]:
    return [x for x in s.split(",") if x]


def to_out(rec: Attendance, user_name: str, now: int | None = None) -> AttendanceOut:
    now = now or now_ms()
    return AttendanceOut(
        id=rec.id,
        user_id=rec.user_id,
        user_name=user_name,
        outlet_id=rec.outlet_id,
        clock_in_at=rec.clock_in_at,
        clock_out_at=rec.clock_out_at,
        minutes=(
            None
            if rec.clock_out_at is None
            else max(0, round((rec.clock_out_at - rec.clock_in_at) / 60000))
        ),
        in_distance_m=rec.in_distance,
        out_distance_m=rec.out_distance,
        in_flags=_flags(rec.in_flags),
        out_flags=_flags(rec.out_flags),
        has_in_photo=bool(rec.in_photo),
        has_out_photo=bool(rec.out_photo),
        review_status=rec.review_status,
        review_note=rec.review_note,
        edited=bool(rec.edits),
        stale=rec.clock_out_at is None and now - rec.clock_in_at > STALE_MS,
    )


def _open_record(
    db: Session, user_id: str, ref_ms: int, lock: bool = False
) -> Attendance | None:
    """Catatan masuk yang belum pulang dan tidak basi terhadap waktu acuan."""
    stmt = (
        select(Attendance)
        .where(
            Attendance.user_id == user_id,
            Attendance.clock_out_at.is_(None),
            Attendance.clock_in_at >= ref_ms - STALE_MS,
        )
        .order_by(Attendance.clock_in_at.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def clock(
    db: Session,
    actor: User,
    *,
    event_id: str,
    kind: str,
    client_time: int,
    lat: float,
    lng: float,
    accuracy_m: float,
    mocked: bool,
    liveness_ok: bool,
    photo_raw: bytes,
) -> Attendance:
    if actor.outlet_id is None:
        raise Forbidden("Akun ini tidak terikat outlet, tidak melakukan absensi")

    # kirim ulang event yang sama -> kembalikan hasil sebelumnya (idempoten)
    dup = db.scalar(
        select(Attendance).where(
            or_(Attendance.in_event_id == event_id, Attendance.out_event_id == event_id)
        )
    )
    if dup is not None:
        if dup.user_id != actor.id:
            raise Conflict("event_id sudah dipakai")
        return dup

    outlet = outlet_service.get_outlet(db, actor.outlet_id)
    if outlet is None or not outlet.active:
        raise Forbidden("Outlet tidak aktif")
    if outlet.lat is None or outlet.lng is None:
        raise Conflict("Lokasi outlet belum diatur oleh owner")

    now = now_ms()
    if client_time > now + MAX_FUTURE_MS:
        raise BadRequest("Jam perangkat tidak valid (di masa depan)")
    if now - client_time > MAX_PAST_MS:
        raise BadRequest("Absen tertunda lebih dari 24 jam. Minta manager mengoreksi.")
    if mocked:
        raise BadRequest("Lokasi palsu (mock location) terdeteksi")
    if not liveness_ok:
        raise BadRequest("Verifikasi wajah belum lolos")
    if accuracy_m > settings.max_gps_accuracy_m:
        raise BadRequest(
            f"Akurasi GPS kurang (±{int(accuracy_m)} m). Coba di tempat terbuka."
        )
    dist = distance_m(lat, lng, outlet.lat, outlet.lng)
    if dist > outlet.radius_m + settings.geofence_tolerance_m:
        raise BadRequest(
            f"Anda berada di luar area outlet (±{int(dist)} m dari titik, batas {outlet.radius_m} m)"
        )
    flags = ["late_sync"] if now - client_time > LATE_SYNC_MS else []

    open_rec = _open_record(db, actor.id, client_time, lock=True)
    if kind == "in":
        if open_rec is not None:
            raise Conflict("Anda sudah absen masuk dan belum absen pulang")
        last = db.scalar(
            select(Attendance)
            .where(Attendance.user_id == actor.id)
            .order_by(Attendance.clock_in_at.desc())
            .limit(1)
        )
        if last is not None and (last.clock_out_at or last.clock_in_at) >= client_time:
            raise BadRequest("Waktu absen tumpang tindih dengan catatan sebelumnya")
    else:
        if open_rec is None:
            raise Conflict("Belum absen masuk")
        if client_time <= open_rec.clock_in_at:
            raise BadRequest("Jam pulang harus setelah jam masuk")

    rel = photos.save_photo(photo_raw, outlet.id)  # setelah semua validasi lolos
    try:
        if kind == "in":
            rec = Attendance(
                user_id=actor.id,
                outlet_id=outlet.id,
                clock_in_at=client_time,
                in_lat=lat,
                in_lng=lng,
                in_accuracy=accuracy_m,
                in_distance=int(dist),
                in_photo=rel,
                in_flags=",".join(flags),
                in_received_at=now,
                in_event_id=event_id,
            )
            db.add(rec)
        else:
            rec = open_rec
            rec.clock_out_at = client_time
            rec.out_lat = lat
            rec.out_lng = lng
            rec.out_accuracy = accuracy_m
            rec.out_distance = int(dist)
            rec.out_photo = rel
            rec.out_flags = ",".join(flags)
            rec.out_received_at = now
            rec.out_event_id = event_id
        db.commit()
    except Exception:
        db.rollback()
        photos.delete_photo(rel)
        raise
    db.refresh(rec)
    return rec


def me(db: Session, actor: User) -> MeOut:
    now = now_ms()
    rows = db.scalars(
        select(Attendance)
        .where(
            Attendance.user_id == actor.id,
            Attendance.clock_in_at >= now - 14 * 86400 * 1000,
        )
        .order_by(Attendance.clock_in_at.desc())
        .limit(60)
    ).all()
    outs = [to_out(r, actor.name, now) for r in rows]
    open_rec = _open_record(db, actor.id, now)
    return MeOut(
        open=next((o for o in outs if open_rec and o.id == open_rec.id), None),
        recent=outs,
    )


def _scope_outlet(actor: User, outlet_id: str | None) -> str | None:
    if actor.role == Role.manager.value:
        if outlet_id not in (None, actor.outlet_id):
            raise Forbidden("Anda hanya boleh melihat absensi outlet Anda sendiri")
        return actor.outlet_id
    return outlet_id  # owner: semua outlet atau yang dipilih


def list_records(
    db: Session,
    actor: User,
    *,
    outlet_id: str | None = None,
    user_id: str | None = None,
    since: int | None = None,
    until: int | None = None,
    review_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AttendanceOut]:
    outlet = _scope_outlet(actor, outlet_id)
    stmt = select(Attendance, User.name).join(User, User.id == Attendance.user_id)
    if outlet:
        stmt = stmt.where(Attendance.outlet_id == outlet)
    if user_id:
        stmt = stmt.where(Attendance.user_id == user_id)
    if since is not None:
        stmt = stmt.where(Attendance.clock_in_at >= since)
    if until is not None:
        stmt = stmt.where(Attendance.clock_in_at < until)
    if review_status:
        stmt = stmt.where(Attendance.review_status == review_status)
    stmt = stmt.order_by(Attendance.clock_in_at.desc()).limit(limit).offset(offset)
    now = now_ms()
    return [to_out(rec, name, now) for rec, name in db.execute(stmt).all()]


def summary(
    db: Session,
    actor: User,
    *,
    outlet_id: str | None,
    since: int | None,
    until: int | None,
) -> list[SummaryRow]:
    rows = list_records(
        db, actor, outlet_id=outlet_id, since=since, until=until, limit=10000
    )
    agg: dict[str, SummaryRow] = {}
    for r in rows:
        s = agg.setdefault(
            r.user_id,
            SummaryRow(
                user_id=r.user_id,
                user_name=r.user_name,
                records=0,
                minutes=0,
                open_count=0,
            ),
        )
        s.records += 1
        s.minutes += r.minutes or 0
        s.open_count += 1 if r.clock_out_at is None else 0
    return sorted(agg.values(), key=lambda s: s.user_name.lower())


def get_record_for(
    db: Session, actor: User, record_id: str, *, allow_self: bool = False
) -> Attendance:
    rec = db.get(Attendance, record_id)
    if rec is not None:
        if actor.role == Role.owner.value:
            return rec
        if actor.role == Role.manager.value and rec.outlet_id == actor.outlet_id:
            return rec
        if allow_self and rec.user_id == actor.id:
            return rec
    raise NotFound(
        "Catatan absensi tidak ditemukan"
    )  # 404: tidak membocorkan keberadaan


def photo_file(db: Session, actor: User, record_id: str, kind: str):
    rec = get_record_for(db, actor, record_id, allow_self=True)
    rel = rec.in_photo if kind == "in" else rec.out_photo
    path = photos.resolve(rel) if rel else None
    if path is None or not path.exists():
        raise NotFound("Foto tidak tersedia (mungkin sudah dihapus sesuai masa simpan)")
    return path


def correct(
    db: Session,
    actor: User,
    rec: Attendance,
    *,
    clock_in_at: int | None,
    clock_out_at: int | None,
    reason: str,
) -> Attendance:
    if clock_in_at is None and clock_out_at is None:
        raise BadRequest("Tidak ada perubahan")
    new_in = clock_in_at if clock_in_at is not None else rec.clock_in_at
    new_out = clock_out_at if clock_out_at is not None else rec.clock_out_at
    now = now_ms()
    if new_in > now + MAX_FUTURE_MS or (
        new_out is not None and new_out > now + MAX_FUTURE_MS
    ):
        raise BadRequest("Waktu tidak boleh di masa depan")
    if new_out is not None and new_out <= new_in:
        raise BadRequest("Jam pulang harus setelah jam masuk")
    end = new_out if new_out is not None else new_in
    clash = db.scalar(
        select(Attendance)
        .where(
            Attendance.user_id == rec.user_id,
            Attendance.id != rec.id,
            Attendance.clock_in_at <= end,
            func.coalesce(Attendance.clock_out_at, Attendance.clock_in_at) >= new_in,
        )
        .limit(1)
    )
    if clash is not None:
        raise Conflict("Tumpang tindih dengan catatan absensi lain")
    edits = list(rec.edits or [])
    edits.append(
        {
            "at": now,
            "by": actor.id,
            "reason": reason,
            "before": {"in": rec.clock_in_at, "out": rec.clock_out_at},
            "after": {"in": new_in, "out": new_out},
        }
    )
    rec.edits = edits  # ditetapkan ulang agar perubahan JSON terdeteksi
    rec.clock_in_at = new_in
    rec.clock_out_at = new_out
    db.commit()
    db.refresh(rec)
    return rec


def review(
    db: Session, actor: User, rec: Attendance, status: str, note: str
) -> Attendance:
    rec.review_status = status
    rec.review_note = note
    rec.reviewed_by = actor.id
    db.commit()
    db.refresh(rec)
    return rec


def purge_old_photos(db: Session, days: int) -> int:
    """Hapus foto absensi lebih tua dari [days] hari. Catatan absensinya tetap ada."""
    cutoff = now_ms() - days * 86400 * 1000
    rows = db.scalars(
        select(Attendance).where(
            Attendance.clock_in_at < cutoff,
            or_(Attendance.in_photo.is_not(None), Attendance.out_photo.is_not(None)),
        )
    ).all()
    for r in rows:
        photos.delete_photo(r.in_photo)
        photos.delete_photo(r.out_photo)
        r.in_photo = None
        r.out_photo = None
    db.commit()
    return len(rows)
