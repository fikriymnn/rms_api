from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.features.attendance.models import Attendance, ConsentEvent
from app.features.users.roles import Role

from .helpers import auth_header
from .test_attendance import MIN, clock, geo_outlet, now, staff


def test_revoking_consent_deletes_photos_and_coordinates(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    assert clock(client, h, "in", ts=now() - 120 * MIN).status_code == 200
    assert clock(client, h, "out", ts=now() - 60 * MIN).status_code == 200
    db.rollback()
    row = db.scalars(select(Attendance)).one()
    files = [Path(settings.photo_dir) / p for p in (row.in_photo, row.out_photo)]
    assert all(f.exists() for f in files)

    r = client.post("/attendance/consent/revoke", headers=h)
    assert r.status_code == 200 and r.json()["photos_deleted"] == 2
    assert not any(f.exists() for f in files)  # file fisik hilang

    db.rollback()
    row = db.scalars(select(Attendance)).one()
    assert row.in_photo is None and row.out_photo is None
    assert row.in_lat is None and row.in_lng is None and row.out_lat is None
    assert (
        row.clock_in_at and row.clock_out_at and row.in_distance is not None
    )  # catatan kerja tetap
    me = client.get("/attendance/me", headers=h).json()
    assert me["consent"] is None and me["recent"][0]["has_in_photo"] is False
    assert (
        clock(client, h, "in").status_code == 403
    )  # absen berhenti sampai setuju lagi
    events = db.scalars(
        select(ConsentEvent).where(ConsentEvent.kind == "revoked")
    ).all()
    assert len(events) == 1 and events[0].photos_deleted == 2


def test_can_consent_again_after_revoking(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    client.post("/attendance/consent/revoke", headers=h)
    v = settings.attendance_consent_version
    assert (
        client.post("/attendance/consent", json={"version": v}, headers=h).status_code
        == 200
    )
    assert clock(client, h, "in").status_code == 200
    db.rollback()
    kinds = [
        e.kind
        for e in db.scalars(
            select(ConsentEvent).order_by(ConsentEvent.at, ConsentEvent.kind.desc())
        )
    ]
    assert kinds == ["revoked", "granted"]


def test_revocation_only_affects_the_caller(client, db):
    o = geo_outlet(db)
    staff(db, o, "ca")
    staff(db, o, "wa", Role.waiter)
    ha, hb = auth_header(client, "ca"), auth_header(client, "wa")
    clock(client, ha, "in", ts=now() - 90 * MIN)
    clock(client, hb, "in", ts=now() - 90 * MIN)
    client.post("/attendance/consent/revoke", headers=ha)
    db.rollback()
    assert sum(1 for r in db.scalars(select(Attendance)) if r.in_photo is None) == 1
    me_b = client.get("/attendance/me", headers=hb).json()
    assert me_b["consent"] is not None and me_b["recent"][0]["has_in_photo"] is True


def test_revoke_requires_login_and_is_idempotent(client, db):
    assert client.post("/attendance/consent/revoke").status_code == 401
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    assert client.post("/attendance/consent/revoke", headers=h).status_code == 200
    again = client.post("/attendance/consent/revoke", headers=h)
    assert again.status_code == 200 and again.json()["photos_deleted"] == 0
