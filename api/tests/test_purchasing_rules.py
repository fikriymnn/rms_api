from app.features.sync.models import Doc
from app.features.users.roles import Role

from .helpers import make_user
from .test_sync import auth_header, d, ids, pull, push, world


def me_id(client, h):
    return client.get("/auth/me", headers=h).json()["id"]


def pline(ing, qty, price, factor=1000.0):
    return {
        "ingredientId": ing,
        "name": ing,
        "unitLabel": "kg",
        "factor": factor,
        "qty": qty,
        "unitPrice": price,
    }


def po(pid, uid, status="draft", lines=None, supplier="s1", **kw):
    data = {
        "id": pid,
        "number": f"PO-{pid}",
        "supplierId": supplier,
        "supplierName": "Toko",
        "createdAt": 1000,
        "status": status,
        "lines": lines if lines is not None else [pline("i1", 10, 14000)],
        "note": "",
        "total": 140000,
        "createdBy": uid,
        "createdByName": "x",
    }
    data.update(kw)
    return data


def receipt(gid, po_id, lines, supplier="s1"):
    return {
        "id": gid,
        "number": f"GR-{gid}",
        "poId": po_id,
        "supplierId": supplier,
        "supplierName": "Toko",
        "at": 5000,
        "lines": lines,
        "invoiceNo": "",
        "userName": "x",
        "total": 0,
    }


def setup(db):
    a, b = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    make_user(db, "wh_b", Role.warehouse, b.id)
    return a, b


def test_po_creation_rules(client, db):
    a, _ = setup(db)
    wh, mgr, chef, boss = (
        auth_header(client, u) for u in ("wh", "mgr_a", "chef", "boss")
    )
    wid, mid, cid, oid = (me_id(client, h) for h in (wh, mgr, chef, boss))
    assert (
        push(client, wh, [d("purchase_orders", "po1", po("po1", wid))])[0]["status"]
        == "ok"
    )
    assert (
        push(client, chef, [d("purchase_orders", "po2", po("po2", cid))])[0]["status"]
        == "ok"
    )
    # tidak boleh langsung dipesan (kecuali owner) dan tidak boleh atas nama orang lain
    assert (
        push(
            client, wh, [d("purchase_orders", "po3", po("po3", wid, status="ordered"))]
        )[0]["status"]
        == "rejected"
    )
    assert (
        push(
            client, mgr, [d("purchase_orders", "po4", po("po4", mid, status="ordered"))]
        )[0]["status"]
        == "rejected"
    )
    assert (
        push(client, wh, [d("purchase_orders", "po5", po("po5", "orang-lain"))])[0][
            "status"
        ]
        == "rejected"
    )
    assert (
        push(
            client,
            boss,
            [d("purchase_orders", "po6", po("po6", oid, status="ordered"))],
            outlet_id=a.id,
        )[0]["status"]
        == "ok"
    )
    # status yang hanya boleh diatur server
    for st in ("pending", "rejected"):
        res = push(
            client, wh, [d("purchase_orders", f"x_{st}", po(f"x_{st}", wid, status=st))]
        )
        assert res[0]["status"] == "rejected"


def test_draft_editing_rules(client, db):
    setup(db)
    wh, mgr = auth_header(client, "wh"), auth_header(client, "mgr_a")
    wid = me_id(client, wh)
    push(client, wh, [d("purchase_orders", "po1", po("po1", wid))])
    edit = po("po1", wid, lines=[pline("i1", 12, 14000)], total=168000)
    assert (
        push(client, mgr, [d("purchase_orders", "po1", edit, ts=2000)])[0]["status"]
        == "rejected"
    )  # draft orang lain
    assert (
        push(client, wh, [d("purchase_orders", "po1", edit, ts=2000)])[0]["status"]
        == "ok"
    )
    cancel = po("po1", wid, status="cancelled", lines=edit["lines"], total=168000)
    assert (
        push(client, wh, [d("purchase_orders", "po1", cancel, ts=3000)])[0]["status"]
        == "ok"
    )


def test_ordered_po_is_locked(client, db):
    a, _ = setup(db)
    boss, wh = auth_header(client, "boss"), auth_header(client, "wh")
    oid = me_id(client, boss)
    assert (
        push(
            client,
            boss,
            [d("purchase_orders", "po1", po("po1", oid, status="ordered"))],
            outlet_id=a.id,
        )[0]["status"]
        == "ok"
    )
    tampered = po("po1", oid, status="ordered", lines=[pline("i1", 99, 1)])
    assert (
        push(client, wh, [d("purchase_orders", "po1", tampered, ts=2000)])[0]["status"]
        == "rejected"
    )
    assert (
        push(
            client,
            wh,
            [d("purchase_orders", "po1", po("po1", oid, status="closed"), ts=3000)],
        )[0]["status"]
        == "ok"
    )


def test_pending_po_cannot_be_changed_from_device(client, db):
    a, _ = setup(db)
    db.add(
        Doc(
            collection="purchase_orders",
            id="pp",
            outlet_id=a.id,
            data=po("pp", "u1", status="pending"),
            updated_at=1000,
            deleted=False,
            seq=9999,
        )
    )
    db.commit()
    wh, boss = auth_header(client, "wh"), auth_header(client, "boss")
    assert (
        push(
            client,
            wh,
            [d("purchase_orders", "pp", po("pp", "u1", status="draft"), ts=2000)],
        )[0]["status"]
        == "rejected"
    )
    res = push(
        client,
        boss,
        [d("purchase_orders", "pp", po("pp", "u1", status="ordered"), ts=2000)],
        outlet_id=a.id,
    )
    assert res[0]["status"] == "rejected"


def test_receipt_requires_approved_po_and_server_creates_purchase_moves(client, db):
    a, _ = setup(db)
    boss, wh, chef, ca = (auth_header(client, u) for u in ("boss", "wh", "chef", "ca"))
    oid = me_id(client, boss)
    push(
        client,
        boss,
        [d("purchase_orders", "po1", po("po1", oid, status="ordered"))],
        outlet_id=a.id,
    )
    push(
        client, boss, [d("purchase_orders", "po0", po("po0", oid))], outlet_id=a.id
    )  # masih draft
    assert (
        push(
            client,
            wh,
            [d("goods_receipts", "g0", receipt("g0", "po0", [pline("i1", 5, 14000)]))],
        )[0]["status"]
        == "rejected"
    )
    assert (
        push(
            client,
            wh,
            [d("goods_receipts", "g1", receipt("g1", "po1", [pline("i1", 6, 14000)]))],
        )[0]["status"]
        == "ok"
    )

    moves = {
        x["id"]: x["data"]
        for x in pull(client, wh)["docs"]
        if x["collection"] == "stock_moves"
    }
    m = moves["rcv_g1_i1"]
    assert m["type"] == "purchase" and m["qty"] == 6000 and m["unitCost"] == 14.0
    # head chef melihat stok masuk, penerimaan, dan PO; kasir tidak
    got = {c for c, _ in ids(pull(client, chef))}
    assert {"stock_moves", "goods_receipts", "purchase_orders"} <= got
    got_ca = {c for c, _ in ids(pull(client, ca))}
    assert not ({"stock_moves", "goods_receipts", "purchase_orders"} & got_ca)


def test_receipt_quantity_and_validity_rules(client, db):
    a, _ = setup(db)
    boss, wh, wh_b, chef = (
        auth_header(client, u) for u in ("boss", "wh", "wh_b", "chef")
    )
    oid = me_id(client, boss)
    push(
        client,
        boss,
        [d("purchase_orders", "po1", po("po1", oid, status="ordered"))],
        outlet_id=a.id,
    )

    def gr(gid, lines, h=wh, po_id="po1", supplier="s1"):
        return push(
            client, h, [d("goods_receipts", gid, receipt(gid, po_id, lines, supplier))]
        )[0]

    assert gr("g1", [pline("i1", 6, 14000)])["status"] == "ok"
    assert (
        gr("g2", [pline("i1", 6, 14000)])["status"] == "rejected"
    )  # total 12 > 11 (110% dari 10)
    assert gr("g3", [pline("i1", 4, 14000)])["status"] == "ok"  # total 10
    assert (
        gr("g4", [pline("i-lain", 1, 1)])["status"] == "rejected"
    )  # bahan tidak ada di PO
    assert gr("g5", [pline("i1", 1, 1)], supplier="s2")["status"] == "rejected"
    assert (
        gr("g6", [pline("i1", 1, 1)], h=wh_b)["status"] == "rejected"
    )  # PO milik outlet lain
    assert gr("g7", [pline("i1", 1, 1)], po_id="tidak-ada")["status"] == "rejected"
    assert (
        gr("g8", [pline("i1", 1, 1)], h=chef)["reason"] == "forbidden"
    )  # head chef tidak menerima barang


def test_manual_stock_moves_rules(client, db):
    a, _ = setup(db)
    boss, wh, mgr = (auth_header(client, u) for u in ("boss", "wh", "mgr_a"))
    purchase = {"type": "purchase", "qty": 5000, "unitCost": 10}
    assert (
        push(client, wh, [d("stock_moves", "m1", {"id": "m1", **purchase})])[0][
            "status"
        ]
        == "rejected"
    )
    assert (
        push(client, mgr, [d("stock_moves", "m2", {"id": "m2", **purchase})])[0][
            "status"
        ]
        == "rejected"
    )
    assert (
        push(
            client,
            boss,
            [d("stock_moves", "m3", {"id": "m3", **purchase})],
            outlet_id=a.id,
        )[0]["status"]
        == "ok"
    )
    assert (
        push(
            client,
            wh,
            [d("stock_moves", "m4", {"id": "m4", "type": "waste", "qty": -100})],
        )[0]["status"]
        == "ok"
    )
    assert (
        push(
            client,
            mgr,
            [d("stock_moves", "m5", {"id": "m5", "type": "sale", "qty": -1})],
        )[0]["status"]
        == "rejected"
    )


def test_supplier_payments_and_supplier_visibility(client, db):
    setup(db)
    boss, mgr, wh, chef = (
        auth_header(client, u) for u in ("boss", "mgr_a", "wh", "chef")
    )
    pay = {"id": "pay1", "supplierId": "s1", "amount": 1000}
    assert (
        push(client, wh, [d("supplier_payments", "pay1", pay)])[0]["reason"]
        == "forbidden"
    )
    assert (
        push(client, chef, [d("supplier_payments", "pay1", pay)])[0]["reason"]
        == "forbidden"
    )
    assert push(client, mgr, [d("supplier_payments", "pay1", pay)])[0]["status"] == "ok"
    assert ("supplier_payments", "pay1") in ids(pull(client, mgr))
    for h in (wh, chef):
        assert not any(c == "supplier_payments" for c, _ in ids(pull(client, h)))
    # supplier: semua peran pembelian boleh membaca, hanya owner yang menulis
    assert (
        push(client, boss, [d("suppliers", "s1", {"id": "s1", "name": "Toko"})])[0][
            "status"
        ]
        == "ok"
    )
    for h in (mgr, wh, chef):
        assert ("suppliers", "s1") in ids(pull(client, h))
        assert push(client, h, [d("suppliers", "s2")])[0]["reason"] == "forbidden"
