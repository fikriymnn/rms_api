import time

from app.features.users.roles import Role

from .helpers import auth_header, make_outlet, make_user


def d(collection, id_, data=None, ts=1000, deleted=False):
    return {
        "collection": collection,
        "id": id_,
        "data": data if data is not None else {"id": id_},
        "updated_at": ts,
        "deleted": deleted,
    }


def push(client, h, docs, outlet_id=None):
    r = client.post(
        "/sync/push", json={"outlet_id": outlet_id, "docs": docs}, headers=h
    )
    assert r.status_code == 200, r.text
    return r.json()["results"]


def pull(client, h, since=0, outlet_id=None, limit=500):
    params = {"since": since, "limit": limit}
    if outlet_id:
        params["outlet_id"] = outlet_id
    r = client.get("/sync/pull", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def ids(body):
    return {(x["collection"], x["id"]) for x in body["docs"]}


def world(db):
    a, b = make_outlet(db, "A"), make_outlet(db, "B")
    make_user(db, "boss", Role.owner)
    make_user(db, "mgr_a", Role.manager, a.id)
    make_user(db, "mgr_b", Role.manager, b.id)
    make_user(db, "ca", Role.cashier, a.id)
    make_user(db, "wa", Role.waiter, a.id)
    make_user(db, "ka", Role.kitchen, a.id)
    make_user(db, "wh", Role.warehouse, a.id)
    return a, b


# ---------- dasar ----------


def test_requires_auth(client):
    assert client.get("/sync/pull").status_code == 401
    assert client.post("/sync/push", json={"docs": []}).status_code == 401


def test_roundtrip(client, db):
    world(db)
    h = auth_header(client, "mgr_a")
    res = push(client, h, [d("tables", "t1", {"id": "t1", "name": "T1"})])
    assert res[0]["status"] == "ok" and res[0]["seq"] > 0
    body = pull(client, h)
    assert ids(body) == {("tables", "t1")}
    assert body["next_since"] == res[0]["seq"] and body["has_more"] is False
    assert pull(client, h, since=body["next_since"])["docs"] == []


def test_pagination_by_seq(client, db):
    world(db)
    h = auth_header(client, "mgr_a")
    push(client, h, [d("tables", f"t{i}") for i in range(5)])
    seen, since = [], 0
    while True:
        body = pull(client, h, since=since, limit=2)
        seen += [x["id"] for x in body["docs"]]
        since = body["next_since"]
        if not body["has_more"]:
            break
    assert seen == [f"t{i}" for i in range(5)]


def test_last_write_wins_and_idempotent_retry(client, db):
    world(db)
    h = auth_header(client, "mgr_a")
    assert (
        push(client, h, [d("tables", "t1", {"id": "t1", "name": "v2"}, ts=2000)])[0][
            "status"
        ]
        == "ok"
    )
    assert (
        push(client, h, [d("tables", "t1", {"id": "t1", "name": "v1"}, ts=1000)])[0][
            "status"
        ]
        == "stale"
    )
    assert (
        push(client, h, [d("tables", "t1", {"id": "t1", "name": "v2"}, ts=2000)])[0][
            "status"
        ]
        == "stale"
    )
    assert pull(client, h)["docs"][0]["data"]["name"] == "v2"
    assert (
        push(client, h, [d("tables", "t1", {"id": "t1", "name": "v3"}, ts=3000)])[0][
            "status"
        ]
        == "ok"
    )
    assert pull(client, h)["docs"][0]["data"]["name"] == "v3"


def test_soft_delete_propagates(client, db):
    world(db)
    h = auth_header(client, "mgr_a")
    push(client, h, [d("tables", "t1")])
    assert (
        push(client, h, [d("tables", "t1", ts=2000, deleted=True)])[0]["status"] == "ok"
    )
    assert pull(client, h)["docs"][0]["deleted"] is True


def test_append_only(client, db):
    world(db)
    h = auth_header(client, "mgr_a")
    log = {"id": "l1", "reason": "x"}
    first = push(client, h, [d("audit_logs", "l1", log)])[0]
    assert first["status"] == "ok"
    again = push(client, h, [d("audit_logs", "l1", log)])[0]
    assert again["status"] == "ok" and again["seq"] == first["seq"]  # identik: aman
    assert (
        push(
            client,
            h,
            [d("audit_logs", "l1", {"id": "l1", "reason": "diubah"}, ts=5000)],
        )[0]["status"]
        == "rejected"
    )
    assert (
        push(client, h, [d("audit_logs", "l1", log, ts=5000, deleted=True)])[0][
            "status"
        ]
        == "rejected"
    )


# ---------- isolasi outlet ----------


def test_outlet_isolation_on_pull(client, db):
    a, b = world(db)
    boss = auth_header(client, "boss")
    push(client, boss, [d("tables", "ta")], outlet_id=a.id)
    push(client, boss, [d("tables", "tb")], outlet_id=b.id)
    assert ids(pull(client, auth_header(client, "mgr_a"))) == {("tables", "ta")}
    assert ids(pull(client, auth_header(client, "mgr_b"))) == {("tables", "tb")}
    assert ids(pull(client, boss, outlet_id=b.id)) == {("tables", "tb")}
    r = client.get(
        "/sync/pull", params={"outlet_id": b.id}, headers=auth_header(client, "mgr_a")
    )
    assert r.status_code == 403


def test_manager_cannot_push_to_other_outlet(client, db):
    _, b = world(db)
    h = auth_header(client, "mgr_a")
    r = client.post(
        "/sync/push", json={"outlet_id": b.id, "docs": [d("tables", "x")]}, headers=h
    )
    assert r.status_code == 403


def test_cannot_overwrite_other_outlets_document(client, db):
    a, b = world(db)
    boss = auth_header(client, "boss")
    push(
        client,
        boss,
        [d("tables", "t1", {"id": "t1", "name": "milik B"})],
        outlet_id=b.id,
    )
    res = push(
        client,
        auth_header(client, "mgr_a"),
        [d("tables", "t1", {"id": "t1", "name": "diretas"}, ts=9000)],
    )
    assert res[0]["status"] == "rejected" and res[0]["reason"] == "id_conflict"
    assert pull(client, boss, outlet_id=b.id)["docs"][0]["data"]["name"] == "milik B"


def test_shared_data_visible_to_all_outlets(client, db):
    world(db)
    push(
        client,
        auth_header(client, "boss"),
        [d("menu_items", "m1", {"id": "m1", "name": "Nasi"})],
    )
    for who in ("mgr_a", "mgr_b", "ca"):
        body = pull(client, auth_header(client, who))
        assert ("menu_items", "m1") in ids(body)
        assert body["docs"][0]["outlet_id"] is None


def test_owner_needs_outlet_for_outlet_data(client, db):
    world(db)
    boss = auth_header(client, "boss")
    res = push(client, boss, [d("tables", "t1")])
    assert res[0]["reason"] == "outlet_required"
    assert push(client, boss, [d("menu_items", "m1")])[0]["status"] == "ok"


# ---------- aturan per role ----------


def test_write_permissions(client, db):
    world(db)
    ca, mgr, ka = (auth_header(client, u) for u in ("ca", "mgr_a", "ka"))
    assert push(client, ca, [d("tables", "t1")])[0]["reason"] == "forbidden"
    assert push(client, ca, [d("menu_items", "m1")])[0]["reason"] == "forbidden"
    assert push(client, mgr, [d("menu_items", "m1")])[0]["reason"] == "forbidden"
    assert push(client, ka, [d("orders", "o1")])[0]["reason"] == "forbidden"
    assert push(client, ka, [d("item_status", "i1")])[0]["status"] == "ok"
    assert push(client, ca, [d("menu_availability", "v1")])[0]["status"] == "ok"


def test_read_permissions(client, db):
    world(db)
    mgr = auth_header(client, "mgr_a")
    push(
        client,
        mgr,
        [
            d("stock_moves", "m1", {"id": "m1", "type": "purchase", "qty": 5}),
            d("audit_logs", "l1"),
            d("orders", "o1"),
            d("tables", "t1"),
        ],
    )
    assert {"stock_moves", "audit_logs"} <= {c for c, _ in ids(pull(client, mgr))}
    cashier = ids(pull(client, auth_header(client, "ca")))
    assert ("orders", "o1") in cashier and ("tables", "t1") in cashier
    assert not any(c in ("stock_moves", "audit_logs") for c, _ in cashier)
    wh = ids(pull(client, auth_header(client, "wh")))
    assert ("stock_moves", "m1") in wh and not any(c == "orders" for c, _ in wh)


def test_collections_endpoint(client, db):
    world(db)
    r = client.get("/sync/collections", headers=auth_header(client, "ca")).json()
    assert "orders" in r["read"] and "stock_moves" not in r["read"]
    assert "expenses" in r["write"] and "tables" not in r["write"]


def test_cashier_expenses_only_drawer(client, db):
    world(db)
    ca, mgr = auth_header(client, "ca"), auth_header(client, "mgr_a")
    assert (
        push(client, ca, [d("expenses", "e1", {"id": "e1", "fromDrawer": False})])[0][
            "status"
        ]
        == "rejected"
    )
    assert (
        push(client, ca, [d("expenses", "e2", {"id": "e2", "fromDrawer": True})])[0][
            "status"
        ]
        == "ok"
    )
    assert (
        push(client, mgr, [d("expenses", "e3", {"id": "e3", "fromDrawer": False})])[0][
            "status"
        ]
        == "ok"
    )
    assert ids(pull(client, ca)) == {
        ("expenses", "e2")
    }  # biaya non-laci tidak terlihat kasir
    assert ids(pull(client, mgr)) == {("expenses", "e2"), ("expenses", "e3")}


def test_orders_discount_and_refund_rules(client, db):
    world(db)
    wa, mgr = auth_header(client, "wa"), auth_header(client, "mgr_a")
    assert (
        push(client, wa, [d("orders", "o1", {"id": "o1", "discount": 5000})])[0][
            "status"
        ]
        == "rejected"
    )
    assert (
        push(client, wa, [d("orders", "o1", {"id": "o1", "discount": 0})])[0]["status"]
        == "ok"
    )
    assert (
        push(client, mgr, [d("orders", "o1", {"id": "o1", "discount": 5000}, ts=2000)])[
            0
        ]["status"]
        == "ok"
    )
    assert (
        push(
            client,
            wa,
            [
                d(
                    "orders",
                    "o1",
                    {"id": "o1", "discount": 5000, "status": "refunded"},
                    ts=3000,
                )
            ],
        )[0]["status"]
        == "rejected"
    )
    assert (
        push(
            client,
            mgr,
            [
                d(
                    "orders",
                    "o1",
                    {"id": "o1", "discount": 5000, "status": "refunded"},
                    ts=3000,
                )
            ],
        )[0]["status"]
        == "ok"
    )


def test_shift_only_by_owning_cashier(client, db):
    world(db)
    ca = auth_header(client, "ca")
    my_id = client.get("/auth/me", headers=ca).json()["id"]
    assert (
        push(client, ca, [d("shifts", "s1", {"id": "s1", "cashierId": "orang-lain"})])[
            0
        ]["status"]
        == "rejected"
    )
    assert (
        push(client, ca, [d("shifts", "s2", {"id": "s2", "cashierId": my_id})])[0][
            "status"
        ]
        == "ok"
    )


def test_cashier_cannot_write_stock_moves(client, db):
    world(db)
    ca = auth_header(client, "ca")
    assert (
        push(client, ca, [d("stock_moves", "m1", {"id": "m1", "type": "purchase"})])[0][
            "reason"
        ]
        == "forbidden"
    )
    assert (
        push(client, ca, [d("stock_moves", "m2", {"id": "m2", "type": "sale"})])[0][
            "reason"
        ]
        == "forbidden"
    )


# ---------- masukan tidak wajar ----------


def test_bad_inputs_are_rejected(client, db):
    world(db)
    h = auth_header(client, "mgr_a")
    future = int(time.time() * 1000) + 3 * 24 * 3600 * 1000
    res = push(
        client,
        h,
        [
            d("foo", "x"),
            d("tables", "a b"),
            d("tables", "t1", ts=future),
            d("tables", "t2", {"id": "t2", "blob": "x" * 70000}),
        ],
    )
    assert [r["reason"] for r in res] == [
        "unknown_collection",
        "bad_id",
        "bad_timestamp",
        "too_large",
    ]
