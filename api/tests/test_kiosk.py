import uuid

from app.features.users.roles import Role

from .helpers import PASSWORD, auth_header, make_user
from .test_attendance import MIN, clock, geo_outlet, jpeg, now
from .test_roles import new_role

PIN = "482915"


def setup(db, client):
    a = geo_outlet(db, "A")
    b = geo_outlet(db, "B")
    make_user(db, "boss", Role.owner)
    make_user(db, "mgr", Role.manager, a.id)
    make_user(db, "ca", Role.cashier, a.id, consent=False)
    make_user(db, "wa", Role.waiter, a.id)
    make_user(db, "wb", Role.waiter, b.id)
    make_user(db, "off", Role.waiter, a.id, active=False)
    boss = auth_header(client, "boss")
    assert new_role(client, boss, "kiosk", ["attendance.kiosk"]).status_code == 201
    make_user(db, "kio", "kiosk", a.id, consent=False)
    make_user(db, "kio_b", "kiosk", b.id, consent=False)
    return a, b


def uid(db, username):
    from sqlalchemy import select
    from app.features.users.models import User

    return db.scalar(select(User.id).where(User.username == username))


def set_pin(client, h, user_id, pin=PIN):
    return client.put(f"/attendance/pin/{user_id}", json={"pin": pin}, headers=h)


def verify(client, h, user_id, pin=PIN, event=None):
    return client.post(
        "/attendance/kiosk/verify",
        json={"user_id": user_id, "pin": pin, "event_id": event or str(uuid.uuid4())},
        headers=h,
    )


def kclock(client, h, user_id, ticket, event, kind="in", ts=None, **over):
    data = {
        "user_id": user_id,
        "ticket": ticket,
        "event_id": event,
        "kind": kind,
        "client_time": ts if ts is not None else now(),
        "lat": -6.9,
        "lng": 107.6,
        "accuracy_m": 10.0,
        "mocked": "false",
        "liveness_ok": "true",
    }
    data.update(over)
    files = {"photo": ("selfie.jpg", jpeg(), "image/jpeg")}
    return client.post("/attendance/kiosk/clock", data=data, files=files, headers=h)


def test_staff_list_only_this_outlet_and_clockable(client, db):
    setup(db, client)
    h = auth_header(client, "kio")
    r = client.get("/attendance/kiosk/staff", headers=h)
    assert r.status_code == 200, r.text
    names = [x["name"] for x in r.json()]
    assert sorted(names) == [
        "Ca",
        "Mgr",
        "Wa",
    ]  # tanpa wb (outlet lain), off, dan akun kiosk
    ca = next(x for x in r.json() if x["name"] == "Ca")
    assert (
        ca["has_pin"] is False
        and ca["consent_ok"] is False
        and ca["clocked_in"] is False
    )


def test_regular_users_cannot_use_kiosk_endpoints(client, db):
    setup(db, client)
    for u in ("wa", "mgr", "boss"):
        h = auth_header(client, u)
        assert client.get("/attendance/kiosk/staff", headers=h).status_code == 403, u


def test_full_kiosk_flow_with_pin_consent_and_clock(client, db):
    setup(db, client)
    mgr, kio = auth_header(client, "mgr"), auth_header(client, "kio")
    ca = uid(db, "ca")
    assert set_pin(client, mgr, ca).status_code == 204
    assert verify(client, kio, ca, "000000").status_code == 403  # PIN salah
    ev = str(uuid.uuid4())
    t = verify(client, kio, ca, PIN, ev)
    assert t.status_code == 200, t.text
    ticket = t.json()["ticket"]
    # belum setuju -> ditolak
    assert kclock(client, kio, ca, ticket, ev, ts=now() - 60 * MIN).status_code == 403
    r = client.post(
        "/attendance/kiosk/consent",
        json={"user_id": ca, "ticket": ticket, "version": 1},
        headers=kio,
    )
    assert r.status_code == 200, r.text
    r = kclock(client, kio, ca, ticket, ev, ts=now() - 60 * MIN)
    assert r.status_code == 200, r.text
    assert r.json()["user_name"] == "Ca" and r.json()["via_kiosk"] is True
    # tampil di absensi milik karyawan itu sendiri
    me = client.get("/attendance/me", headers=auth_header(client, "ca")).json()
    assert me["open"]["id"] == r.json()["id"]
    # pulang lewat kiosk
    ev2 = str(uuid.uuid4())
    ticket2 = verify(client, kio, ca, PIN, ev2).json()["ticket"]
    r = kclock(client, kio, ca, ticket2, ev2, kind="out", ts=now() - 30 * MIN)
    assert r.status_code == 200 and r.json()["minutes"] == 30


def test_ticket_is_bound_to_user_event_and_kiosk(client, db):
    setup(db, client)
    mgr, kio = auth_header(client, "mgr"), auth_header(client, "kio")
    wa, ca = uid(db, "wa"), uid(db, "ca")
    set_pin(client, mgr, wa), set_pin(client, mgr, ca)
    ev = str(uuid.uuid4())
    ticket = verify(client, kio, wa, PIN, ev).json()["ticket"]
    # tiket milik wa tidak bisa dipakai untuk ca
    assert kclock(client, kio, ca, ticket, ev).status_code == 403
    # event_id harus sama dengan saat verifikasi
    assert kclock(client, kio, wa, ticket, str(uuid.uuid4())).status_code == 403
    # tiket palsu
    assert kclock(client, kio, wa, "x" * 40, ev).status_code == 403
    assert kclock(client, kio, wa, ticket, ev).status_code == 200
    # tiket access token biasa tidak diterima sebagai tiket kiosk
    from app.core.security import create_access_token

    tok, _ = create_access_token(wa)
    assert kclock(client, kio, wa, tok, ev).status_code == 403


def test_pin_lockout_after_five_wrong_attempts(client, db):
    setup(db, client)
    mgr, kio = auth_header(client, "mgr"), auth_header(client, "kio")
    wa = uid(db, "wa")
    set_pin(client, mgr, wa)
    for i in range(4):
        r = verify(client, kio, wa, "111111")
        assert r.status_code == 403 and f"sisa percobaan {4 - i}" in r.json()["detail"]
    assert verify(client, kio, wa, "111111").status_code == 429
    # terkunci: PIN benar pun ditolak
    assert verify(client, kio, wa, PIN).status_code == 429
    # kunci habis -> normal lagi, hitungan percobaan reset
    from app.features.users.models import User

    u = db.get(User, wa)
    u.attendance_pin_locked_until = now() - 1000
    db.commit()
    assert verify(client, kio, wa, PIN).status_code == 200
    db.refresh(u)
    assert u.attendance_pin_failed == 0


def test_no_pin_set_and_cross_outlet_are_rejected(client, db):
    setup(db, client)
    kio, kio_b = auth_header(client, "kio"), auth_header(client, "kio_b")
    wa, wb = uid(db, "wa"), uid(db, "wb")
    assert verify(client, kio, wa).status_code == 403  # PIN belum diatur
    assert verify(client, kio, wb).status_code == 404  # outlet lain
    assert verify(client, kio_b, wa).status_code == 404


def test_pin_management_permissions_and_self_service(client, db):
    setup(db, client)
    boss, mgr, wa_h = (auth_header(client, u) for u in ("boss", "mgr", "wa"))
    wa, wb = uid(db, "wa"), uid(db, "wb")
    assert set_pin(client, wa_h, wa).status_code == 403  # staf biasa tidak boleh
    assert set_pin(client, mgr, wb).status_code == 403  # manager outlet lain
    assert set_pin(client, boss, wb).status_code == 204  # owner bebas
    assert set_pin(client, mgr, wa, "12").status_code == 422  # format
    assert set_pin(client, mgr, wa, "12ab56").status_code == 422
    # ganti sendiri butuh password
    r = client.put(
        "/attendance/pin/me", json={"pin": PIN, "password": "salah"}, headers=wa_h
    )
    assert r.status_code == 403
    r = client.put(
        "/attendance/pin/me", json={"pin": PIN, "password": PASSWORD}, headers=wa_h
    )
    assert r.status_code == 204
    # hapus PIN
    assert client.delete(f"/attendance/pin/{wa}", headers=mgr).status_code == 204
    assert verify(client, auth_header(client, "kio"), wa).status_code == 403


def test_regular_clock_unchanged_and_flagged_not_kiosk(client, db):
    setup(db, client)
    r = clock(client, auth_header(client, "wa"), "in", ts=now() - 10 * MIN)
    assert r.status_code == 200 and r.json()["via_kiosk"] is False
