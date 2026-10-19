from app.core.config import settings
from app.features.users.roles import Role

from .helpers import PASSWORD, auth_header, login, make_outlet, make_user
from .test_attendance import clock, geo_outlet


def test_clock_requires_consent_recorded_on_server(client, db):
    o = geo_outlet(db)
    make_user(db, "ca", Role.cashier, o.id, consent=False)
    h = auth_header(client, "ca")
    r = clock(client, h)
    assert r.status_code == 403 and "Persetujuan" in r.json()["detail"]
    assert client.get("/attendance/me", headers=h).json()["consent"] is None
    assert (
        client.post("/attendance/consent", json={"version": 999}, headers=h).status_code
        == 400
    )
    v = settings.attendance_consent_version
    assert (
        client.post("/attendance/consent", json={"version": v}, headers=h).status_code
        == 200
    )
    assert client.get("/attendance/me", headers=h).json()["consent"]["version"] == v
    assert clock(client, h).status_code == 200


def test_admin_created_user_must_change_password(client, db):
    a = make_outlet(db, "A")
    make_user(db, "boss", Role.owner)
    boss = auth_header(client, "boss")
    body = {
        "username": "baru1",
        "password": PASSWORD,
        "name": "Baru",
        "role": "manager",
        "outlet_id": a.id,
    }
    assert client.post("/users", json=body, headers=boss).status_code == 201

    r = login(client, "baru1")
    assert r.json()["user"]["must_change_password"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auth/me", headers=h).status_code == 200  # tetap boleh
    blocked = client.get("/users", headers=h)
    assert (
        blocked.status_code == 403 and "mengganti password" in blocked.json()["detail"]
    )
    assert client.get("/sync/pull", headers=h).status_code == 403

    same = client.post(
        "/auth/change-password",
        json={"old_password": PASSWORD, "new_password": PASSWORD},
        headers=h,
    )
    assert same.status_code == 400
    ok = client.post(
        "/auth/change-password",
        json={"old_password": PASSWORD, "new_password": "kata-sandi-baru"},
        headers=h,
    )
    assert ok.status_code == 204

    again = login(client, "baru1", "kata-sandi-baru")
    assert again.json()["user"]["must_change_password"] is False
    h2 = {"Authorization": f"Bearer {again.json()['access_token']}"}
    assert client.get("/users", headers=h2).status_code == 200


def test_reset_password_forces_change_again(client, db):
    o = make_outlet(db, "A")
    make_user(db, "mgr", Role.manager, o.id)
    staff = make_user(db, "ca", Role.cashier, o.id)
    assert login(client, "ca").json()["user"]["must_change_password"] is False
    r = client.post(
        f"/users/{staff.id}/reset-password",
        json={"new_password": "sementara-123"},
        headers=auth_header(client, "mgr"),
    )
    assert r.status_code == 204
    assert (
        login(client, "ca", "sementara-123").json()["user"]["must_change_password"]
        is True
    )
