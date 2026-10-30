"""Master role dinamis: CRUD role, izin per fitur/aksi, dan penegakannya."""

from app.features.roles.catalog import SYSTEM_DEFAULTS
from app.features.roles.service import seed_system_roles
from app.features.users.roles import Role

from .helpers import auth_header, make_outlet, make_user
from .test_sync import d, push, pull


def world(db):
    seed_system_roles(db)
    a = make_outlet(db, "A")
    make_user(db, "boss", Role.owner)
    make_user(db, "mgr", Role.manager, a.id)
    make_user(db, "wh", Role.warehouse, a.id)
    make_user(db, "ca", Role.cashier, a.id)
    make_user(db, "wa", Role.waiter, a.id)
    return a


def new_role(client, h, key, perms=(), name=None, is_staff=False):
    return client.post(
        "/roles",
        json={
            "key": key,
            "name": name or key.title(),
            "permissions": list(perms),
            "is_staff": is_staff,
        },
        headers=h,
    )


def set_perms(client, h, key, perms):
    r = client.patch(f"/roles/{key}", json={"permissions": list(perms)}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def status(res):
    return res[0]["status"], res[0].get("reason")


def test_only_owner_manages_roles(client, db):
    world(db)
    boss, mgr = auth_header(client, "boss"), auth_header(client, "mgr")
    assert client.get("/roles", headers=mgr).status_code == 403
    assert new_role(client, mgr, "spv").status_code == 403
    assert client.get("/roles/catalog", headers=mgr).status_code == 403
    r = client.get("/roles", headers=boss)
    assert {x["key"] for x in r.json()} == {
        "owner",
        "manager",
        "head_chef",
        "cashier",
        "waiter",
        "kitchen",
        "warehouse",
    }
    cat = client.get("/roles/catalog", headers=boss).json()
    menu = next(f for f in cat if f["key"] == "menu")
    assert {a["permission"] for a in menu["actions"]} >= {
        "menu.read",
        "menu.create",
        "menu.update",
        "menu.delete",
    }


def test_seeded_system_roles_match_defaults(client, db):
    world(db)
    boss = auth_header(client, "boss")
    by_key = {r["key"]: r for r in client.get("/roles", headers=boss).json()}
    for key, perms in SYSTEM_DEFAULTS.items():
        assert set(by_key[key]["permissions"]) == set(perms), key
    assert by_key["owner"]["locked"] is True and by_key["cashier"]["locked"] is False


def test_create_role_validation(client, db):
    world(db)
    boss = auth_header(client, "boss")
    assert new_role(client, boss, "spv", ["menu.read"]).status_code == 201
    assert new_role(client, boss, "spv").status_code == 409
    assert new_role(client, boss, "spv2", name="SPV").status_code == 409
    assert new_role(client, boss, "owner").status_code == 409
    assert new_role(client, boss, "Bad Key").status_code == 422
    r = new_role(client, boss, "spv3", ["menu.read", "menu.fly"])
    assert r.status_code == 400 and "menu.fly" in r.json()["detail"]


def test_menu_crud_permissions_are_granular(client, db):
    a = world(db)
    boss = auth_header(client, "boss")
    assert (
        new_role(client, boss, "menu_ed", ["menu.read", "menu.create"]).status_code
        == 201
    )
    make_user(db, "ed", "menu_ed", a.id)
    ed = auth_header(client, "ed")
    item = {"id": "m1", "name": "Nasi"}

    assert status(push(client, ed, [d("menu_items", "m1", item, ts=1000)])) == (
        "ok",
        None,
    )
    assert status(push(client, ed, [d("menu_items", "m1", item, ts=2000)])) == (
        "rejected",
        "forbidden",
    )
    assert status(
        push(client, ed, [d("menu_items", "m1", item, ts=3000, deleted=True)])
    ) == ("rejected", "forbidden")

    set_perms(client, boss, "menu_ed", ["menu.read", "menu.create", "menu.update"])
    assert status(push(client, ed, [d("menu_items", "m1", item, ts=4000)]))[0] == "ok"
    assert status(
        push(client, ed, [d("menu_items", "m1", item, ts=5000, deleted=True)])
    ) == ("rejected", "forbidden")

    set_perms(
        client,
        boss,
        "menu_ed",
        ["menu.read", "menu.create", "menu.update", "menu.delete"],
    )
    assert (
        status(push(client, ed, [d("menu_items", "m1", item, ts=6000, deleted=True)]))[
            0
        ]
        == "ok"
    )

    set_perms(client, boss, "menu_ed", [])
    assert status(push(client, ed, [d("menu_items", "m2", {"id": "m2"}, ts=7000)])) == (
        "rejected",
        "forbidden",
    )
    assert not pull(client, ed)["docs"]


def test_login_and_me_return_permissions(client, db):
    a = world(db)
    boss = auth_header(client, "boss")
    new_role(client, boss, "spv", ["orders.read", "orders.create"], name="Supervisor")
    make_user(db, "sp", "spv", a.id)
    user = client.post(
        "/auth/login", json={"username": "sp", "password": "rahasia123"}
    ).json()["user"]
    assert user["role"] == "spv" and user["role_name"] == "Supervisor"
    assert user["permissions"] == ["orders.create", "orders.read"]
    me = client.get("/auth/me", headers=auth_header(client, "sp")).json()
    assert me["permissions"] == ["orders.create", "orders.read"]
    owner_me = client.get("/auth/me", headers=boss).json()
    assert "menu.delete" in owner_me["permissions"]
    assert "approvals.approve_l1" not in owner_me["permissions"]


def test_collections_follow_permissions(client, db):
    a = world(db)
    boss = auth_header(client, "boss")
    new_role(client, boss, "viewer", ["orders.read", "stock.read"])
    make_user(db, "vw", "viewer", a.id)
    r = client.get("/sync/collections", headers=auth_header(client, "vw")).json()
    assert (
        "orders" in r["read"]
        and "stock_moves" in r["read"]
        and "item_status" in r["read"]
    )
    assert r["write"] == []


def test_system_and_in_use_roles_are_protected(client, db):
    a = world(db)
    boss = auth_header(client, "boss")
    assert client.delete("/roles/cashier", headers=boss).status_code == 403
    assert (
        client.patch("/roles/owner", json={"permissions": []}, headers=boss).status_code
        == 403
    )
    assert client.post("/roles/owner/reset", headers=boss).status_code == 403
    new_role(client, boss, "spv", ["orders.read"])
    make_user(db, "sp", "spv", a.id)
    r = client.delete("/roles/spv", headers=boss)
    assert r.status_code == 409 and "1 pengguna" in r.json()["detail"]
    new_role(client, boss, "tmp")
    assert client.delete("/roles/tmp", headers=boss).status_code == 204
    assert client.get("/roles/tmp", headers=boss).status_code == 404


def test_manager_only_assigns_staff_roles(client, db):
    a = world(db)
    boss, mgr = auth_header(client, "boss"), auth_header(client, "mgr")
    new_role(client, boss, "barista", ["orders.read"], is_staff=True)
    new_role(client, boss, "lead", ["orders.read"], is_staff=False)

    def create(h, username, role):
        return client.post(
            "/users",
            json={
                "username": username,
                "password": "rahasia123",
                "name": username,
                "role": role,
                "outlet_id": a.id,
            },
            headers=h,
        )

    assert create(mgr, "bar1", "barista").status_code == 201
    assert create(mgr, "lead1", "lead").status_code == 403
    assert create(mgr, "mgr2", "manager").status_code == 403
    assert create(boss, "lead2", "lead").status_code == 201
    assert create(boss, "ghost", "tidak_ada").status_code == 422

    def assignable(h):
        rows = client.get("/users/role-options", headers=h).json()
        return {r["key"] for r in rows if r["assignable"]}

    keys_mgr, keys_boss = assignable(mgr), assignable(boss)
    assert "barista" in keys_mgr and "lead" not in keys_mgr
    assert {"lead", "barista", "manager"} <= keys_boss and "owner" not in keys_boss


def test_dynamic_role_can_be_level_one_approver(client, db):
    a = world(db)
    boss, wh = auth_header(client, "boss"), auth_header(client, "wh")
    new_role(client, boss, "spv", ["approvals.read", "approvals.approve_l1"])
    new_role(client, boss, "plain", ["approvals.read"])
    make_user(db, "sp", "spv", a.id)
    make_user(db, "pl", "plain", a.id)
    body = {
        "type": "supplier",
        "supplier": {"action": "create", "name": "UD Sayur", "phone": "0812"},
    }
    req = client.post("/approvals", json=body, headers=wh)
    assert req.status_code in (200, 201), req.text
    rid = req.json()["id"]
    assert req.json()["status"] == "pending_l1"
    plain = client.post(
        f"/approvals/{rid}/approve",
        json={"note": ""},
        headers=auth_header(client, "pl"),
    )
    assert plain.status_code in (403, 404)
    ok = client.post(
        f"/approvals/{rid}/approve",
        json={"note": ""},
        headers=auth_header(client, "sp"),
    )
    assert ok.status_code == 200 and ok.json()["status"] == "pending_owner"


def test_attendance_clock_needs_permission(client, db):
    a = world(db)
    boss = auth_header(client, "boss")
    new_role(client, boss, "noclock", ["orders.read"])
    make_user(db, "nc", "noclock", a.id)
    assert (
        client.post(
            "/attendance/clock", headers=auth_header(client, "nc"), data={}
        ).status_code
        == 403
    )


def test_reset_system_role_restores_defaults(client, db):
    world(db)
    boss = auth_header(client, "boss")
    set_perms(client, boss, "cashier", ["orders.read"])
    assert client.get("/roles/cashier", headers=boss).json()["permissions"] == [
        "orders.read"
    ]
    r = client.post("/roles/cashier/reset", headers=boss)
    assert r.status_code == 200
    assert set(r.json()["permissions"]) == set(SYSTEM_DEFAULTS["cashier"])
