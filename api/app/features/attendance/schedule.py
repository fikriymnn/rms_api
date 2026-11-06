"""Jadwal buka-tutup outlet dan penilaian ketepatan waktu absensi."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Forbidden, NotFound
from app.features.outlets.models import Outlet, OutletHours
from app.features.users.models import User
from app.features.users.roles import Role

from .models import Attendance
from .schemas import ScheduleDayOut, ScheduleIn, ScheduleOut

MIN_MS = 60_000


@dataclass(frozen=True)
class Expected:
    sched_in: int  # epoch ms: jam buka dikurangi lead
    sched_out: int  # epoch ms: jam tutup ditambah tail
    grace_min: int


def _hhmm(m: int | None) -> str | None:
    return None if m is None else f"{m // 60:02d}:{m % 60:02d}"


def _minutes(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise BadRequest(f"Zona waktu tidak dikenal: {name}")


def _scope(db: Session, actor: User, outlet_id: str) -> Outlet:
    if actor.role != Role.owner.value and outlet_id != actor.outlet_id:
        raise Forbidden("Hanya boleh mengatur jadwal outlet Anda sendiri")
    outlet = db.get(Outlet, outlet_id)
    if outlet is None:
        raise NotFound("Outlet tidak ditemukan")
    return outlet


def get_schedule(db: Session, actor: User, outlet_id: str) -> ScheduleOut:
    outlet = _scope(db, actor, outlet_id)
    rows = {
        r.weekday: r
        for r in db.scalars(
            select(OutletHours).where(OutletHours.outlet_id == outlet.id)
        )
    }
    days = []
    for d in range(7):
        r = rows.get(d)
        days.append(
            ScheduleDayOut(
                weekday=d,
                configured=r is not None,
                closed=bool(r and r.closed),
                open=_hhmm(r.open_min) if r and not r.closed else None,
                close=_hhmm(r.close_min) if r and not r.closed else None,
            )
        )
    return ScheduleOut(
        outlet_id=outlet.id,
        timezone=outlet.timezone,
        lead_min=outlet.staff_lead_min,
        tail_min=outlet.staff_tail_min,
        grace_min=outlet.grace_min,
        days=days,
    )


def put_schedule(
    db: Session, actor: User, outlet_id: str, data: ScheduleIn
) -> ScheduleOut:
    outlet = _scope(db, actor, outlet_id)
    _tz(data.timezone)
    seen: set[int] = set()
    rows: list[OutletHours] = []
    for d in data.days:
        if d.weekday in seen:
            raise BadRequest("Hari tidak boleh dobel")
        seen.add(d.weekday)
        if d.closed:
            rows.append(
                OutletHours(outlet_id=outlet.id, weekday=d.weekday, closed=True)
            )
            continue
        if d.open is None or d.close is None:
            raise BadRequest("Jam buka dan jam tutup wajib diisi untuk hari buka")
        o, c = _minutes(d.open), _minutes(d.close)
        if o == c:
            raise BadRequest("Jam buka dan jam tutup tidak boleh sama")
        rows.append(
            OutletHours(
                outlet_id=outlet.id,
                weekday=d.weekday,
                closed=False,
                open_min=o,
                close_min=c,
            )
        )
    db.execute(delete(OutletHours).where(OutletHours.outlet_id == outlet.id))
    db.add_all(rows)
    outlet.timezone = data.timezone
    outlet.staff_lead_min = data.lead_min
    outlet.staff_tail_min = data.tail_min
    outlet.grace_min = data.grace_min
    db.commit()
    return get_schedule(db, actor, outlet_id)


def expected_for(db: Session, outlet: Outlet, at_ms: int) -> Expected | None:
    """Jadwal hari kerja untuk absen masuk pada [at_ms]. None = tidak ada jadwal / libur."""
    tz = _tz(outlet.timezone)
    local = datetime.fromtimestamp(at_ms / 1000, tz)
    row = db.get(OutletHours, (outlet.id, local.weekday()))
    if row is None or row.closed or row.open_min is None or row.close_min is None:
        return None
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    open_dt = midnight + timedelta(minutes=row.open_min)
    close_dt = midnight + timedelta(minutes=row.close_min)
    if row.close_min <= row.open_min:  # tutup lewat tengah malam
        close_dt += timedelta(days=1)
    return Expected(
        sched_in=int(
            (open_dt - timedelta(minutes=outlet.staff_lead_min)).timestamp() * 1000
        ),
        sched_out=int(
            (close_dt + timedelta(minutes=outlet.staff_tail_min)).timestamp() * 1000
        ),
        grace_min=outlet.grace_min,
    )


def stamp(rec: Attendance, exp: Expected | None) -> None:
    rec.sched_in_at = exp.sched_in if exp else None
    rec.sched_out_at = exp.sched_out if exp else None
    rec.sched_grace_min = exp.grace_min if exp else None


def evaluate(rec: Attendance) -> dict:
    """Ketepatan waktu catatan terhadap snapshot jadwalnya."""
    out: dict = {
        "sched_in_at": rec.sched_in_at,
        "sched_out_at": rec.sched_out_at,
        "in_status": None,
        "late_min": 0,
        "out_status": None,
        "early_out_min": 0,
        "overtime_min": 0,
    }
    grace = (rec.sched_grace_min or 0) * MIN_MS
    if rec.sched_in_at is not None:
        d = rec.clock_in_at - rec.sched_in_at
        if d > grace:
            out["in_status"] = "late"
            out["late_min"] = round(d / MIN_MS)
        else:
            out["in_status"] = "on_time"
    if rec.sched_out_at is not None and rec.clock_out_at is not None:
        d = rec.clock_out_at - rec.sched_out_at
        if d > grace:
            out["out_status"] = "overtime"
            out["overtime_min"] = round(d / MIN_MS)
        elif -d > grace:
            out["out_status"] = "early"
            out["early_out_min"] = round(-d / MIN_MS)
        else:
            out["out_status"] = "on_time"
    return out
