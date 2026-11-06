from app.features.users.roles import Role

from .helpers import PASSWORD, auth_header, login, make_outlet, make_user


def body(**kw):
    data = {
        "username": "baru1",
        "password": "rahasia123",
        "name": "Baru",
        "role": "cashier",
    }
    data.update(kw)
    return data


def two_outlets_with_managers(db):
    a, b = make_outlet(db, "A"), make_outlet(db, "B")
    make_user(db, "mgr_a", Role.manager, a.id)
    make_user(db, "mgr_b", Role.manager, b.id)
    return a, b


# ---------- membuat akun ----------


def test_owner_creates_manager_and_staff(client, db):
    a = make_outlet(db, "A")
    make_user(db, "boss", Role.owner)
    h = auth_header(client, "boss")
    r = client.post(
        "/users", json=body(username="mgr1", role="manager", outlet_id=a.id), headers=h
    )
    assert r.status_code == 201
    assert r.json()["outlet_id"] == a.id
    assert "password_hash" not in r.json()
    assert (
        client.post(
            "/users", json=body(username="cash1", outlet_id=a.id), headers=h
        ).status_code
        == 201
    )


def test_owner_must_give_outlet(client, db):
    make_user(db, "boss", Role.owner)
    h = auth_header(client, "boss")
    assert (
        client.post("/users", json=body(role="manager"), headers=h).status_code == 400
    )


def test_nobody_can_create_owner_via_api(client, db):
    make_user(db, "boss", Role.owner)
    h = auth_header(client, "boss")
    assert client.post("/users", json=body(role="owner"), headers=h).status_code == 403


def test_manager_creates_staff_in_own_outlet(client, db):
    a, _ = two_outlets_with_managers(db)
    h = auth_header(client, "mgr_a")
    r = client.post("/users", json=body(), headers=h)
    assert r.status_code == 201
    assert r.json()["outlet_id"] == a.id  # dipaksa ke outlet manager


def test_manager_cannot_create_in_other_outlet(client, db):
    _, b = two_outlets_with_managers(db)
    h = auth_header(client, "mgr_a")
    assert (
        client.post("/users", json=body(outlet_id=b.id), headers=h).status_code == 403
    )


def test_manager_cannot_create_manager_or_owner(client, db):
    a, _ = two_outlets_with_managers(db)
    h = auth_header(client, "mgr_a")
    assert (
        client.post(
            "/users", json=body(role="manager", outlet_id=a.id), headers=h
        ).status_code
        == 403
    )
    assert client.post("/users", json=body(role="owner"), headers=h).status_code == 403


def test_staff_cannot_use_user_admin(client, db):
    a = make_outlet(db, "A")
    make_user(db, "cash1", Role.cashier, a.id)
    h = auth_header(client, "cash1")
    assert client.get("/users", headers=h).status_code == 403
    assert client.post("/users", json=body(), headers=h).status_code == 403


def test_duplicate_username_and_validation(client, db):
    a = make_outlet(db, "A")
    make_user(db, "boss", Role.owner)
    make_user(db, "ada", Role.cashier, a.id)
    h = auth_header(client, "boss")
    assert (
        client.post(
            "/users", json=body(username="ADA", outlet_id=a.id), headers=h
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/users", json=body(username="a b", outlet_id=a.id), headers=h
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/users", json=body(password="pendek", outlet_id=a.id), headers=h
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/users", json=body(role="superadmin", outlet_id=a.id), headers=h
        ).status_code
        == 422
    )


# ---------- melihat ----------


def test_manager_lists_only_own_outlet(client, db):
    a, b = two_outlets_with_managers(db)
    make_user(db, "ca", Role.cashier, a.id)
    make_user(db, "cb", Role.cashier, b.id)
    h = auth_header(client, "mgr_a")
    names = {u["username"] for u in client.get("/users", headers=h).json()}
    assert names == {"mgr_a", "ca"}
    assert client.get(f"/users?outlet_id={b.id}", headers=h).status_code == 403


def test_owner_lists_all_and_can_filter(client, db):
    a, b = two_outlets_with_managers(db)
    make_user(db, "boss", Role.owner)
    h = auth_header(client, "boss")
    assert len(client.get("/users", headers=h).json()) == 3
    only_b = client.get(f"/users?outlet_id={b.id}", headers=h).json()
    assert [u["username"] for u in only_b] == ["mgr_b"]


def test_manager_gets_404_for_other_outlet_and_owner(client, db):
    a, b = two_outlets_with_managers(db)
    cb = make_user(db, "cb", Role.cashier, b.id)
    boss = make_user(db, "boss", Role.owner)
    h = auth_header(client, "mgr_a")
    assert client.get(f"/users/{cb.id}", headers=h).status_code == 404
    assert (
        client.patch(f"/users/{cb.id}", json={"name": "X"}, headers=h).status_code
        == 404
    )
    assert client.post(f"/users/{cb.id}/deactivate", headers=h).status_code == 404
    assert (
        client.post(
            f"/users/{cb.id}/reset-password",
            json={"new_password": "baru-12345"},
            headers=h,
        ).status_code
        == 404
    )
    assert client.get(f"/users/{boss.id}", headers=h).status_code == 404


# ---------- mengubah ----------


def test_manager_can_edit_staff_but_not_escalate(client, db):
    a, b = two_outlets_with_managers(db)
    ca = make_user(db, "ca", Role.cashier, a.id)
    h = auth_header(client, "mgr_a")
    r = client.patch(
        f"/users/{ca.id}",
        json={"name": "Nama Baru", "position": "Kasir Senior", "role": "waiter"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "waiter" and r.json()["name"] == "Nama Baru"
    assert (
        client.patch(f"/users/{ca.id}", json={"role": "manager"}, headers=h).status_code
        == 403
    )
    assert (
        client.patch(f"/users/{ca.id}", json={"role": "owner"}, headers=h).status_code
        == 403
    )
    assert (
        client.patch(f"/users/{ca.id}", json={"outlet_id": b.id}, headers=h).status_code
        == 403
    )


def test_manager_cannot_manage_other_manager_in_same_outlet(client, db):
    a, _ = two_outlets_with_managers(db)
    other = make_user(db, "mgr_a2", Role.manager, a.id)
    h = auth_header(client, "mgr_a")
    assert client.get(f"/users/{other.id}", headers=h).status_code == 200  # terlihat
    assert (
        client.patch(f"/users/{other.id}", json={"name": "X"}, headers=h).status_code
        == 403
    )
    assert client.post(f"/users/{other.id}/deactivate", headers=h).status_code == 403
    assert (
        client.post(
            f"/users/{other.id}/reset-password",
            json={"new_password": "baru-12345"},
            headers=h,
        ).status_code
        == 403
    )


def test_owner_moves_user_to_other_outlet(client, db):
    a, b = two_outlets_with_managers(db)
    ca = make_user(db, "ca", Role.cashier, a.id)
    make_user(db, "boss", Role.owner)
    h = auth_header(client, "boss")
    r = client.patch(f"/users/{ca.id}", json={"outlet_id": b.id}, headers=h)
    assert r.status_code == 200 and r.json()["outlet_id"] == b.id
    assert (
        client.patch(
            f"/users/{ca.id}", json={"outlet_id": "tidak-ada"}, headers=h
        ).status_code
        == 400
    )


def test_owner_account_is_not_manageable_via_api(client, db):
    boss = make_user(db, "boss", Role.owner)
    boss2 = make_user(db, "boss2", Role.owner)
    h = auth_header(client, "boss")
    assert (
        client.patch(f"/users/{boss2.id}", json={"name": "X"}, headers=h).status_code
        == 403
    )
    assert (
        client.post(f"/users/{boss.id}/deactivate", headers=h).status_code == 403
    )  # diri sendiri


def test_cannot_deactivate_self(client, db):
    a, _ = two_outlets_with_managers(db)
    mgr = make_user(db, "mgr_a3", Role.manager, a.id)
    h = auth_header(client, "mgr_a3")
    assert client.post(f"/users/{mgr.id}/deactivate", headers=h).status_code == 403


# ---------- sesi login ----------


def test_reset_password_revokes_sessions(client, db):
    a, _ = two_outlets_with_managers(db)
    staff = make_user(db, "ca", Role.cashier, a.id)
    tokens = login(client, "ca").json()
    h = auth_header(client, "mgr_a")
    r = client.post(
        f"/users/{staff.id}/reset-password",
        json={"new_password": "baru-98765"},
        headers=h,
    )
    assert r.status_code == 204
    assert login(client, "ca", PASSWORD).status_code == 401
    assert login(client, "ca", "baru-98765").status_code == 200
    assert (
        client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_deactivate_and_activate(client, db):
    a, _ = two_outlets_with_managers(db)
    staff = make_user(db, "ca", Role.cashier, a.id)
    staff_headers = auth_header(client, "ca")
    refresh = login(client, "ca").json()["refresh_token"]
    h = auth_header(client, "mgr_a")
    assert client.post(f"/users/{staff.id}/deactivate", headers=h).status_code == 200
    assert client.get("/auth/me", headers=staff_headers).status_code == 401
    assert login(client, "ca").status_code == 401
    assert (
        client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    )
    assert client.post(f"/users/{staff.id}/activate", headers=h).status_code == 200
    assert login(client, "ca").status_code == 200
