import io
import time
import uuid
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.features.attendance import service as attendance_service
from app.features.attendance.models import Attendance
from app.features.users.roles import Role

from .helpers import auth_header, make_outlet, make_user

MIN = 60_000


def now():
    return int(time.time() * 1000)


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 50, 50)).save(buf, "JPEG")
    return buf.getvalue()


def png():
    buf = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buf, "PNG")
    return buf.getvalue()


def geo_outlet(db, name="A", lat=-6.9, lng=107.6, radius=100):
    o = make_outlet(db, name)
    o.lat, o.lng, o.radius_m = lat, lng, radius
    db.commit()
    return o


def clock(
    client,
    h,
    kind="in",
    *,
    ts=None,
    lat=-6.9,
    lng=107.6,
    acc=10.0,
    mocked=False,
    liveness=True,
    event=None,
    photo=None,
):
    data = {
        "event_id": event or str(uuid.uuid4()),
        "kind": kind,
        "client_time": ts if ts is not None else now(),
        "lat": lat,
        "lng": lng,
        "accuracy_m": acc,
        "mocked": str(mocked).lower(),
        "liveness_ok": str(liveness).lower(),
    }
    files = {
        "photo": ("selfie.jpg", photo if photo is not None else jpeg(), "image/jpeg")
    }
    return client.post("/attendance/clock", data=data, files=files, headers=h)


def staff(db, outlet, username="ca", role=Role.cashier):
    return make_user(db, username, role, outlet.id)


# ---------- alur dasar ----------


def test_clock_in_and_out(client, db):
    o = geo_outlet(db)
    staff(db, o)
    h = auth_header(client, "ca")
    r = clock(client, h, "in", ts=now() - 120 * MIN)
    assert r.status_code == 200, r.text
    assert r.json()["clock_out_at"] is None and r.json()["has_in_photo"] is True
    r = clock(client, h, "out", ts=now() - 60 * MIN)
    assert r.status_code == 200, r.text
    assert r.json()["minutes"] == 60 and r.json()["has_out_photo"] is True


def test_owner_and_anonymous_cannot_clock(client, db):
    geo_outlet(db)
    make_user(db, "boss", Role.owner)
    assert clock(client, auth_header(client, "boss")).status_code == 403
    assert client.post("/attendance/clock").status_code == 401


def test_idempotent_retry(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    ev = str(uuid.uuid4())
    r1 = clock(client, h, "in", event=ev)
    r2 = clock(client, h, "in", event=ev)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert len(client.get("/attendance/me", headers=h).json()["recent"]) == 1


# ---------- validasi lokasi & wajah ----------


def test_geofence(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    far = clock(client, h, lat=-6.89)  # ±1,1 km
    assert far.status_code == 400 and "luar area" in far.json()["detail"]
    assert clock(client, h, lat=-6.8995).status_code == 200  # ±55 m


def test_gps_accuracy_mock_and_liveness(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    assert clock(client, h, acc=200).status_code == 400
    assert clock(client, h, mocked=True).status_code == 400
    assert clock(client, h, liveness=False).status_code == 400
    assert (
        client.get("/attendance/me", headers=h).json()["recent"] == []
    )  # semua ditolak


def test_outlet_location_not_set(client, db):
    staff(db, make_outlet(db, "Tanpa Lokasi"))
    assert clock(client, auth_header(client, "ca")).status_code == 409


def test_photo_must_be_real_jpeg(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    assert clock(client, h, photo=png()).status_code == 400
    assert clock(client, h, photo=b"bukan gambar").status_code == 400


# ---------- urutan dan waktu ----------


def test_state_machine(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    assert clock(client, h, "out").status_code == 409  # belum masuk
    assert clock(client, h, "in", ts=now() - 180 * MIN).status_code == 200
    assert (
        clock(client, h, "in", ts=now() - 170 * MIN).status_code == 409
    )  # sudah masuk
    assert clock(client, h, "out", ts=now() - 120 * MIN).status_code == 200
    assert clock(client, h, "in", ts=now() - 60 * MIN).status_code == 200  # shift kedua


def test_overlap_with_previous_record(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    clock(client, h, "in", ts=now() - 180 * MIN)
    clock(client, h, "out", ts=now() - 120 * MIN)
    assert clock(client, h, "in", ts=now() - 150 * MIN).status_code == 400


def test_time_rules_and_late_sync_flag(client, db):
    staff(db, geo_outlet(db))
    h = auth_header(client, "ca")
    assert clock(client, h, ts=now() + 10 * MIN).status_code == 400
    assert clock(client, h, ts=now() - 25 * 60 * MIN).status_code == 400
    r = clock(client, h, ts=now() - 10 * MIN)
    assert r.status_code == 200 and "late_sync" in r.json()["in_flags"]


# ---------- hak akses ----------


def two_outlets(db):
    a, b = geo_outlet(db, "A"), geo_outlet(db, "B")
    make_user(db, "boss", Role.owner)
    make_user(db, "mgr_a", Role.manager, a.id)
    make_user(db, "mgr_b", Role.manager, b.id)
    make_user(db, "ca", Role.cashier, a.id)
    make_user(db, "ca2", Role.cashier, a.id)
    make_user(db, "cb", Role.cashier, b.id)
    return a, b


def test_list_scoping(client, db):
    a, b = two_outlets(db)
    clock(client, auth_header(client, "ca"))
    clock(client, auth_header(client, "cb"))
    mgr_a = auth_header(client, "mgr_a")
    assert {
        r["user_name"] for r in client.get("/attendance", headers=mgr_a).json()
    } == {"Ca"}
    assert client.get(f"/attendance?outlet_id={b.id}", headers=mgr_a).status_code == 403
    boss = auth_header(client, "boss")
    assert {r["user_name"] for r in client.get("/attendance", headers=boss).json()} == {
        "Ca",
        "Cb",
    }
    assert (
        client.get("/attendance", headers=auth_header(client, "ca")).status_code == 403
    )


def test_photo_access_control(client, db):
    two_outlets(db)
    rid = clock(client, auth_header(client, "ca")).json()["id"]
    url = f"/attendance/{rid}/photo/in"
    ok = client.get(url, headers=auth_header(client, "ca"))
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert client.get(url, headers=auth_header(client, "mgr_a")).status_code == 200
    assert client.get(url, headers=auth_header(client, "boss")).status_code == 200
    assert (
        client.get(url, headers=auth_header(client, "ca2")).status_code == 404
    )  # rekan sendiri
    assert (
        client.get(url, headers=auth_header(client, "mgr_b")).status_code == 404
    )  # outlet lain
    assert client.get(url).status_code == 401


def test_photo_is_reencoded_and_small(client, db):
    two_outlets(db)
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1500), (10, 200, 10)).save(buf, "JPEG")
    rid = clock(client, auth_header(client, "ca"), photo=buf.getvalue()).json()["id"]
    img = Image.open(
        io.BytesIO(
            client.get(
                f"/attendance/{rid}/photo/in", headers=auth_header(client, "mgr_a")
            ).content
        )
    )
    assert max(img.size) <= 480


# ---------- koreksi, tinjauan, rekap ----------


def make_session(client, h, in_min_ago, out_min_ago):
    rid = clock(client, h, "in", ts=now() - in_min_ago * MIN).json()["id"]
    clock(client, h, "out", ts=now() - out_min_ago * MIN)
    return rid


def test_manager_correction(client, db):
    two_outlets(db)
    rid = make_session(client, auth_header(client, "ca"), 180, 120)
    mgr = auth_header(client, "mgr_a")
    body = {"clock_out_at": now() - 90 * MIN, "reason": "Lupa absen pulang"}
    r = client.patch(f"/attendance/{rid}", json=body, headers=mgr)
    assert (
        r.status_code == 200
        and r.json()["edited"] is True
        and r.json()["minutes"] == 90
    )
    assert (
        client.patch(
            f"/attendance/{rid}", json={**body, "reason": "x"}, headers=mgr
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/attendance/{rid}", json=body, headers=auth_header(client, "mgr_b")
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/attendance/{rid}", json=body, headers=auth_header(client, "ca")
        ).status_code
        == 403
    )


def test_review_and_filter(client, db):
    two_outlets(db)
    rid = make_session(client, auth_header(client, "ca"), 180, 120)
    mgr = auth_header(client, "mgr_a")
    r = client.patch(
        f"/attendance/{rid}/review",
        json={"status": "suspicious", "note": "Wajah tidak jelas"},
        headers=mgr,
    )
    assert r.status_code == 200 and r.json()["review_status"] == "suspicious"
    found = client.get("/attendance?review_status=suspicious", headers=mgr).json()
    assert [x["id"] for x in found] == [rid]
    assert client.get("/attendance?review_status=ok", headers=mgr).json() == []


def test_summary(client, db):
    two_outlets(db)
    h = auth_header(client, "ca")
    make_session(client, h, 360, 300)  # 60 menit
    make_session(client, h, 240, 210)  # 30 menit
    rows = client.get(
        "/attendance/summary", headers=auth_header(client, "mgr_a")
    ).json()
    assert len(rows) == 1 and rows[0]["minutes"] == 90 and rows[0]["records"] == 2


# ---------- retensi foto ----------


def test_purge_old_photos(client, db):
    two_outlets(db)
    h = auth_header(client, "ca")
    rid = clock(client, h, "in", ts=now() - 120 * MIN).json()["id"]
    db.rollback()  # akhiri pandangan lama; sesi uji ini dibuka sebelum API menulis baris itu
    rec = db.get(Attendance, rid)
    path = Path(settings.photo_dir) / rec.in_photo
    assert path.exists()
    rec.clock_in_at = now() - 200 * 24 * 3600 * 1000
    db.commit()
    assert attendance_service.purge_old_photos(db, 90) == 1
    assert not path.exists()
    assert client.get(f"/attendance/{rid}/photo/in", headers=h).status_code == 404
