from app.features.users.roles import Role

from .helpers import make_user
from .test_sync import auth_header, d, ids, pull, push, world


def recipe(mid, lines, ts=1000):
    return d("recipes", mid, {"id": mid, "lines": lines}, ts=ts)


def me_id(client, h):
    return client.get("/auth/me", headers=h).json()["id"]


def make_outlet_of(db):
    from app.features.outlets.models import Outlet
    from sqlalchemy import select

    return db.scalar(select(Outlet).where(Outlet.name == "A")).id


def proposal(pid, **kw):
    data = {
        "id": pid,
        "kind": "new",
        "name": "Wagyu Steak",
        "category": "Main",
        "description": "",
        "proposedPrice": 250000,
        "finalPrice": None,
        "recipe": [{"ingredientId": "i1", "qty": 200}],
        "status": "pending",
        "submittedBy": None,
        "submittedByName": "Chef",
    }
    data.update(kw)
    return data


# ---------- role dan akses ----------


def test_only_owner_creates_head_chef(client, db):
    a, _ = world(db)
    body = {
        "username": "chef1",
        "password": "rahasia123",
        "name": "Chef",
        "role": "head_chef",
        "outlet_id": a.id,
    }
    assert (
        client.post(
            "/users", json=body, headers=auth_header(client, "mgr_a")
        ).status_code
        == 403
    )
    r = client.post("/users", json=body, headers=auth_header(client, "boss"))
    assert r.status_code == 201 and r.json()["role"] == "head_chef"
    # manager melihat tetapi tidak bisa mengelola head chef
    assert (
        client.patch(
            f"/users/{r.json()['id']}",
            json={"name": "X"},
            headers=auth_header(client, "mgr_a"),
        ).status_code
        == 403
    )


def test_head_chef_collections(client, db):
    a, _ = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    r = client.get("/sync/collections", headers=auth_header(client, "chef")).json()
    assert {"recipes", "menu_proposals", "ingredients", "stock_moves", "orders"} <= set(
        r["read"]
    )
    assert {"recipes", "menu_proposals", "menu_availability", "item_status"} <= set(
        r["write"]
    )
    assert "ingredients" not in r["write"]
    assert not (
        {"menu_items", "orders", "stock_moves", "recipe_history"} & set(r["write"])
    )


def test_recipe_visibility(client, db):
    a, _ = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    assert (
        push(
            client,
            auth_header(client, "boss"),
            [recipe("m1", [{"ingredientId": "i1", "qty": 100}])],
        )[0]["status"]
        == "ok"
    )
    for who in ("boss", "mgr_a", "chef"):
        assert ("recipes", "m1") in ids(pull(client, auth_header(client, who)))
    for who in ("ca", "wa", "ka", "wh"):
        got = {c for c, _ in ids(pull(client, auth_header(client, who)))}
        assert not ({"recipes", "recipe_history"} & got), who


def test_recipe_and_ingredient_write_rules(client, db):
    a, _ = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    chef, mgr, wh = (auth_header(client, u) for u in ("chef", "mgr_a", "wh"))
    assert (
        push(client, chef, [recipe("m1", [{"ingredientId": "i1", "qty": 100}])])[0][
            "status"
        ]
        == "ok"
    )
    assert push(client, mgr, [recipe("m2", [])])[0]["reason"] == "forbidden"
    assert push(client, wh, [recipe("m3", [])])[0]["reason"] == "forbidden"
    assert (
        push(client, chef, [d("ingredients", "i1", {"id": "i1", "name": "Beras"})])[0][
            "reason"
        ]
        == "forbidden"
    )
    boss = auth_header(client, "boss")
    assert (
        push(client, boss, [d("ingredients", "i1", {"id": "i1", "name": "Beras"})])[0][
            "status"
        ]
        == "ok"
    )
    assert push(client, wh, [d("ingredients", "i2")])[0]["reason"] == "forbidden"
    assert ("ingredients", "i1") in ids(pull(client, wh))  # gudang boleh membaca bahan
    assert (
        push(client, chef, [d("menu_items", "m9")])[0]["reason"] == "forbidden"
    )  # menu aktif: owner
    assert (
        push(
            client,
            chef,
            [d("menu_availability", "m1", {"id": "m1", "available": False})],
        )[0]["status"]
        == "ok"
    )


def test_recipe_history_is_written_by_server(client, db):
    a, _ = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    chef = auth_header(client, "chef")
    push(client, chef, [recipe("m1", [{"ingredientId": "i1", "qty": 100}])])
    push(client, chef, [recipe("m1", [{"ingredientId": "i1", "qty": 120}], ts=2000)])
    # hanya catatan tambahan, takaran sama: tidak dicatat
    push(
        client,
        chef,
        [
            d(
                "recipes",
                "m1",
                {
                    "id": "m1",
                    "lines": [{"ingredientId": "i1", "qty": 120}],
                    "note": "x",
                },
                ts=3000,
            )
        ],
    )
    hist = [
        x
        for x in pull(client, auth_header(client, "boss"))["docs"]
        if x["collection"] == "recipe_history"
    ]
    assert len(hist) == 2
    last = sorted(hist, key=lambda x: x["seq"])[-1]["data"]
    assert (
        last["byName"] == "Chef"
        and last["before"][0]["qty"] == 100
        and last["after"][0]["qty"] == 120
    )
    assert push(client, chef, [d("recipe_history", "x1")])[0]["reason"] == "forbidden"


# ---------- usulan menu ----------


def test_proposal_workflow(client, db):
    world(db)
    make_user(db, "chef", Role.head_chef, make_outlet_of(db))
    chef, boss = auth_header(client, "chef"), auth_header(client, "boss")
    cid, oid = me_id(client, chef), me_id(client, boss)

    assert (
        push(
            client, chef, [d("menu_proposals", "p1", proposal("p1", submittedBy=cid))]
        )[0]["status"]
        == "ok"
    )
    assert ("menu_items", "p1") not in ids(
        pull(client, auth_header(client, "ca"))
    )  # belum terbit

    # head chef tidak boleh menyetujui, memberi harga final, atau mengatasnamakan orang lain
    assert (
        push(
            client,
            chef,
            [
                d(
                    "menu_proposals",
                    "p2",
                    proposal("p2", submittedBy=cid, status="approved", finalPrice=1),
                )
            ],
        )[0]["status"]
        == "rejected"
    )
    assert (
        push(
            client,
            chef,
            [
                d(
                    "menu_proposals",
                    "p3",
                    proposal("p3", submittedBy=cid, finalPrice=100000),
                )
            ],
        )[0]["status"]
        == "rejected"
    )
    assert (
        push(
            client,
            chef,
            [d("menu_proposals", "p4", proposal("p4", submittedBy="orang-lain"))],
        )[0]["status"]
        == "rejected"
    )
    # role lain tidak menulis maupun membaca usulan
    assert (
        push(
            client,
            auth_header(client, "mgr_a"),
            [d("menu_proposals", "p5", proposal("p5"))],
        )[0]["reason"]
        == "forbidden"
    )
    assert not any(
        c == "menu_proposals"
        for c, _ in ids(pull(client, auth_header(client, "mgr_a")))
    )

    # owner: setuju tanpa harga final atau tolak tanpa alasan ditolak server
    no_price = proposal("p1", submittedBy=cid, status="approved", decidedBy=oid)
    assert (
        push(client, boss, [d("menu_proposals", "p1", no_price, ts=2000)])[0]["status"]
        == "rejected"
    )
    no_note = proposal("p1", submittedBy=cid, status="rejected", decidedBy=oid)
    assert (
        push(client, boss, [d("menu_proposals", "p1", no_note, ts=2000)])[0]["status"]
        == "rejected"
    )

    approved = proposal(
        "p1", submittedBy=cid, status="approved", decidedBy=oid, finalPrice=275000
    )
    assert (
        push(client, boss, [d("menu_proposals", "p1", approved, ts=2000)])[0]["status"]
        == "ok"
    )
    for who in ("ca", "mgr_b"):  # terbit di semua outlet
        items = [
            x
            for x in pull(client, auth_header(client, who))["docs"]
            if x["collection"] == "menu_items"
        ]
        assert (
            len(items) == 1
            and items[0]["data"]["name"] == "Wagyu Steak"
            and items[0]["data"]["price"] == 275000
        )
    assert ("recipes", "p1") in ids(pull(client, boss))  # resep ikut terbit...
    assert not any(
        c == "recipes" for c, _ in ids(pull(client, auth_header(client, "ca")))
    )  # ...tapi tidak ke kasir
    # usulan yang sudah diputuskan tidak bisa diubah lagi
    again = proposal("p1", submittedBy=cid, status="withdrawn")
    assert (
        push(client, chef, [d("menu_proposals", "p1", again, ts=3000)])[0]["status"]
        == "rejected"
    )


def test_price_change_proposal(client, db):
    a, _ = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    chef, boss = auth_header(client, "chef"), auth_header(client, "boss")
    cid, oid = me_id(client, chef), me_id(client, boss)
    push(
        client,
        boss,
        [
            d(
                "menu_items",
                "m1",
                {
                    "id": "m1",
                    "name": "Nasi",
                    "category": "Main",
                    "price": 20000,
                    "available": True,
                },
            )
        ],
    )
    p = proposal(
        "pc1",
        kind="change",
        targetId="m1",
        name="Nasi",
        proposedPrice=25000,
        recipe=None,
        submittedBy=cid,
    )
    assert push(client, chef, [d("menu_proposals", "pc1", p)])[0]["status"] == "ok"
    approve = {**p, "status": "approved", "decidedBy": oid, "finalPrice": 24000}
    assert (
        push(client, boss, [d("menu_proposals", "pc1", approve, ts=2000)])[0]["status"]
        == "ok"
    )
    items = [
        x
        for x in pull(client, auth_header(client, "ca"))["docs"]
        if x["collection"] == "menu_items"
    ]
    assert [(x["id"], x["data"]["price"]) for x in items] == [("m1", 24000)]


def test_head_chef_cannot_touch_others_proposals(client, db):
    a, _ = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    make_user(db, "chef2", Role.head_chef, a.id)
    c1, c2 = auth_header(client, "chef"), auth_header(client, "chef2")
    id1 = me_id(client, c1)
    assert (
        push(client, c1, [d("menu_proposals", "p1", proposal("p1", submittedBy=id1))])[
            0
        ]["status"]
        == "ok"
    )
    theirs = proposal("p1", submittedBy=id1, status="withdrawn")
    assert (
        push(client, c2, [d("menu_proposals", "p1", theirs, ts=2000)])[0]["status"]
        == "rejected"
    )
    assert (
        push(client, c1, [d("menu_proposals", "p1", theirs, ts=2000)])[0]["status"]
        == "ok"
    )  # menarik usul sendiri


# ---------- potong stok di server ----------


def test_stock_deducted_on_server_when_paid(client, db):
    world(db)
    boss, ca, wh = (auth_header(client, u) for u in ("boss", "ca", "wh"))
    push(
        client,
        boss,
        [
            recipe(
                "m1",
                [{"ingredientId": "i1", "qty": 150}, {"ingredientId": "i2", "qty": 1}],
            )
        ],
    )
    order = {
        "id": "o1",
        "number": "INV-1",
        "status": "paid",
        "paidAt": 5000,
        "items": [
            {"menuItemId": "m1", "qty": 2},
            {"menuItemId": "tanpa-resep", "qty": 1},
        ],
    }
    assert push(client, ca, [d("orders", "o1", order)])[0]["status"] == "ok"

    def moves():
        return {
            x["id"]: x["data"]
            for x in pull(client, wh)["docs"]
            if x["collection"] == "stock_moves"
        }

    m = moves()
    assert set(m) == {"sale_o1_i1", "sale_o1_i2"}
    assert m["sale_o1_i1"]["qty"] == -300 and m["sale_o1_i2"]["qty"] == -2
    assert m["sale_o1_i1"]["type"] == "sale" and m["sale_o1_i1"]["orderId"] == "o1"
    # kasir tidak membaca mutasi stok; outlet B tidak melihatnya
    assert not any(c == "stock_moves" for c, _ in ids(pull(client, ca)))
    assert not any(
        c == "stock_moves" for c, _ in ids(pull(client, auth_header(client, "mgr_b")))
    )
    # mengirim ulang atau mengubah order yang sama tidak memotong dua kali
    push(client, ca, [d("orders", "o1", {**order, "discount": 0}, ts=2000)])
    assert len(moves()) == 2
    # order terbuka tidak memotong stok; refund tidak mengembalikan stok
    push(
        client,
        ca,
        [
            d(
                "orders",
                "o2",
                {
                    "id": "o2",
                    "number": "INV-2",
                    "status": "open",
                    "items": [{"menuItemId": "m1", "qty": 1}],
                },
            )
        ],
    )
    push(
        client,
        auth_header(client, "mgr_a"),
        [d("orders", "o1", {**order, "status": "refunded"}, ts=3000)],
    )
    assert len(moves()) == 2 and moves()["sale_o1_i1"]["qty"] == -300
    # kasir tidak bisa menulis mutasi stok sendiri
    assert (
        push(client, ca, [d("stock_moves", "x", {"id": "x", "type": "sale"})])[0][
            "reason"
        ]
        == "forbidden"
    )
