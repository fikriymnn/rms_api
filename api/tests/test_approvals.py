import time

from .test_purchasing_rules import me_id, pline, po, receipt
from .test_purchasing_rules import setup as base_setup
from .test_sync import auth_header, d, ids, pull, push


def prepare(client, db):
    """Dua outlet, supplier s1 yang sudah terdaftar, dan draf po1 milik gudang A."""
    a, b = base_setup(db)
    boss, wh = auth_header(client, "boss"), auth_header(client, "wh")
    assert (
        push(client, boss, [d("suppliers", "s1", {"id": "s1", "name": "Toko Beras"})])[
            0
        ]["status"]
        == "ok"
    )
    wid = me_id(client, wh)
    assert (
        push(client, wh, [d("purchase_orders", "po1", po("po1", wid))])[0]["status"]
        == "ok"
    )
    return a, b


def submit(client, h, ref="po1"):
    return client.post(
        "/approvals", json={"type": "purchase_order", "ref_id": ref}, headers=h
    )


def act(client, h, aid, action, note=""):
    return client.post(f"/approvals/{aid}/{action}", json={"note": note}, headers=h)


def po_status(client, h, pid="po1"):
    docs = [
        x
        for x in pull(client, h)["docs"]
        if x["collection"] == "purchase_orders" and x["id"] == pid
    ]
    return docs[0]["data"]["status"] if docs else None


def future():
    return int(time.time() * 1000) + 60_000


def test_requires_login(client):
    assert client.post("/approvals", json={"type": "supplier"}).status_code == 401
    assert client.get("/approvals").status_code == 401


def test_warehouse_submission_starts_two_level_chain(client, db):
    prepare(client, db)
    wh, boss = auth_header(client, "wh"), auth_header(client, "boss")
    r = submit(client, wh)
    assert r.status_code == 201, r.text
    body = r.json()
    assert (
        body["status"] == "pending_l1"
        and body["type"] == "purchase_order"
        and body["can_withdraw"] is True
    )
    assert po_status(client, wh) == "pending"
    assert submit(client, wh).status_code == 409  # sudah ada pengajuan yang menunggu
    assert submit(client, boss).status_code == 403  # owner tidak mengajukan
    for u in ("ca", "wa", "ka"):
        assert submit(client, auth_header(client, u)).status_code == 403


def test_level_one_approval_rules(client, db):
    prepare(client, db)
    wh, boss, mgr_a, mgr_b = (
        auth_header(client, u) for u in ("wh", "boss", "mgr_a", "mgr_b")
    )
    aid = submit(client, wh).json()["id"]
    assert act(client, wh, aid, "approve").status_code == 403  # pemohon bukan penyetuju
    assert (
        act(client, auth_header(client, "ca"), aid, "approve").status_code == 404
    )  # tidak berkaitan
    assert act(client, mgr_b, aid, "approve").status_code == 404  # outlet lain
    assert act(client, boss, aid, "approve").status_code == 403  # rantai ketat
    r = act(client, mgr_a, aid, "approve", "oke")
    assert r.status_code == 200 and r.json()["status"] == "pending_owner"
    assert r.json()["l1_by_name"] == "Mgr_A" and r.json()["l1_note"] == "oke"
    assert (
        act(client, mgr_a, aid, "approve").status_code == 403
    )  # tahap akhir hanya owner


def test_owner_final_approval_orders_po_and_unlocks_receiving(client, db):
    prepare(client, db)
    wh, mgr, boss = (auth_header(client, u) for u in ("wh", "mgr_a", "boss"))
    aid = submit(client, wh).json()["id"]
    act(client, mgr, aid, "approve")
    r = act(client, boss, aid, "approve", "setuju")
    assert (
        r.status_code == 200
        and r.json()["status"] == "approved"
        and r.json()["owner_by_name"] == "Boss"
    )
    assert po_status(client, wh) == "ordered"
    tampered = po(
        "po1", me_id(client, wh), status="ordered", lines=[pline("i1", 99, 1)]
    )
    assert (
        push(client, wh, [d("purchase_orders", "po1", tampered, ts=future())])[0][
            "status"
        ]
        == "rejected"
    )  # terkunci
    assert (
        push(
            client,
            wh,
            [d("goods_receipts", "g1", receipt("g1", "po1", [pline("i1", 5, 14000)]))],
        )[0]["status"]
        == "ok"
    )


def test_manager_and_head_chef_requests_go_straight_to_owner(client, db):
    prepare(client, db)
    mgr, chef, boss = (auth_header(client, u) for u in ("mgr_a", "chef", "boss"))
    push(client, mgr, [d("purchase_orders", "pm", po("pm", me_id(client, mgr)))])
    push(client, chef, [d("purchase_orders", "pc", po("pc", me_id(client, chef)))])
    r1, r2 = submit(client, mgr, "pm"), submit(client, chef, "pc")
    assert (
        r1.json()["status"] == "pending_owner"
        and r2.json()["status"] == "pending_owner"
    )
    assert (
        act(client, mgr, r1.json()["id"], "approve").status_code == 403
    )  # tidak menyetujui sendiri
    assert (
        act(client, mgr, r2.json()["id"], "approve").status_code == 403
    )  # manager bukan penyetuju akhir
    for r in (r1, r2):
        assert act(client, boss, r.json()["id"], "approve").status_code == 200
    assert (
        po_status(client, mgr, "pm") == "ordered"
        and po_status(client, mgr, "pc") == "ordered"
    )


def test_rejection_rules(client, db):
    prepare(client, db)
    wh, mgr, boss = (auth_header(client, u) for u in ("wh", "mgr_a", "boss"))
    aid = submit(client, wh).json()["id"]
    assert (
        client.post(
            f"/approvals/{aid}/reject", json={"note": ""}, headers=mgr
        ).status_code
        == 422
    )
    r = act(client, mgr, aid, "reject", "harga terlalu mahal")
    assert (
        r.status_code == 200
        and r.json()["status"] == "rejected"
        and r.json()["l1_note"] == "harga terlalu mahal"
    )
    assert po_status(client, wh) == "rejected"
    assert act(client, boss, aid, "approve").status_code == 409
    assert act(client, mgr, aid, "reject", "lagi lagi").status_code == 409


def test_owner_can_reject_at_any_stage_others_cannot_at_owner_stage(client, db):
    prepare(client, db)
    wh, mgr, boss = (auth_header(client, u) for u in ("wh", "mgr_a", "boss"))
    wid = me_id(client, wh)
    a1 = submit(client, wh).json()["id"]
    r = act(client, boss, a1, "reject", "tidak sesuai anggaran")
    assert r.status_code == 200 and r.json()["owner_note"] == "tidak sesuai anggaran"
    assert po_status(client, wh) == "rejected"
    push(client, wh, [d("purchase_orders", "po2", po("po2", wid))])
    a2 = submit(client, wh, "po2").json()["id"]
    act(client, mgr, a2, "approve")
    assert act(client, mgr, a2, "reject", "tidak setuju").status_code == 403
    assert act(client, boss, a2, "reject", "tidak setuju").status_code == 200


def test_withdraw_returns_po_to_draft(client, db):
    prepare(client, db)
    wh, mgr = auth_header(client, "wh"), auth_header(client, "mgr_a")
    wid = me_id(client, wh)
    aid = submit(client, wh).json()["id"]
    assert act(client, mgr, aid, "withdraw").status_code == 403  # bukan pemohon
    r = act(client, wh, aid, "withdraw")
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert po_status(client, wh) == "draft"
    edit = po("po1", wid, lines=[pline("i1", 8, 14000)], total=112000)
    assert (
        push(client, wh, [d("purchase_orders", "po1", edit, ts=future())])[0]["status"]
        == "ok"
    )
    assert submit(client, wh).status_code == 201  # bisa diajukan ulang


def test_inbox_mine_history_scoping_and_counts(client, db):
    prepare(client, db)
    wh, whb, mgr_a, mgr_b, boss, chef = (
        auth_header(client, u) for u in ("wh", "wh_b", "mgr_a", "mgr_b", "boss", "chef")
    )
    push(client, whb, [d("purchase_orders", "pb", po("pb", me_id(client, whb)))])
    a1 = submit(client, wh).json()["id"]
    b1 = submit(client, whb, "pb").json()["id"]

    def inbox(h):
        return {x["id"] for x in client.get("/approvals?scope=inbox", headers=h).json()}

    assert inbox(mgr_a) == {a1} and inbox(chef) == {a1} and inbox(mgr_b) == {b1}
    assert (
        inbox(wh) == set() and inbox(boss) == set()
    )  # owner baru melihat sesudah tingkat 1
    act(client, mgr_a, a1, "approve")
    act(client, mgr_b, b1, "approve")
    assert inbox(boss) == {a1, b1} and inbox(mgr_a) == set()
    assert {
        x["id"] for x in client.get("/approvals?scope=mine", headers=wh).json()
    } == {a1}

    assert client.get(f"/approvals/{a1}", headers=mgr_b).status_code == 404
    assert (
        client.get(f"/approvals/{a1}", headers=auth_header(client, "ca")).status_code
        == 404
    )
    assert client.get(f"/approvals/{a1}", headers=boss).status_code == 200

    act(client, boss, a1, "approve")
    assert {
        x["id"] for x in client.get("/approvals?scope=history", headers=boss).json()
    } == {a1}
    assert {
        x["id"] for x in client.get("/approvals?scope=history", headers=mgr_a).json()
    } == {a1}
    assert client.get("/approvals?scope=history", headers=mgr_b).json() == []

    detail = client.get(f"/approvals/{b1}", headers=boss).json()
    assert (
        detail["can_approve"] is True
        and detail["can_reject"] is True
        and detail["can_withdraw"] is False
    )
    assert client.get("/approvals/counts", headers=boss).json() == {
        "inbox": 1,
        "mine_open": 0,
    }
    assert client.get("/approvals/counts", headers=whb).json() == {
        "inbox": 0,
        "mine_open": 1,
    }


def test_supplier_requests(client, db):
    prepare(client, db)
    wh, mgr, chef, boss = (
        auth_header(client, u) for u in ("wh", "mgr_a", "chef", "boss")
    )
    new = {
        "type": "supplier",
        "supplier": {"action": "create", "name": "UD Sayur", "phone": "0812"},
    }
    r = client.post("/approvals", json=new, headers=wh)
    assert r.status_code == 201 and r.json()["status"] == "pending_l1"
    aid = r.json()["id"]
    assert act(client, mgr, aid, "approve").status_code == 200
    assert act(client, boss, aid, "approve").status_code == 200
    sup = {
        x["id"]: x["data"]
        for x in pull(client, chef)["docs"]
        if x["collection"] == "suppliers"
    }
    assert {v["name"] for v in sup.values()} == {"Toko Beras", "UD Sayur"}

    dup = {"type": "supplier", "supplier": {"action": "create", "name": "ud sayur"}}
    assert client.post("/approvals", json=dup, headers=wh).status_code == 409
    empty = {"type": "supplier", "supplier": {"action": "create", "name": ""}}
    assert client.post("/approvals", json=empty, headers=wh).status_code == 422

    sid = next(k for k, v in sup.items() if v["name"] == "UD Sayur")
    upd = {
        "type": "supplier",
        "supplier": {
            "action": "update",
            "supplier_id": sid,
            "name": "UD Sayur Segar",
            "phone": "0899",
        },
    }
    r2 = client.post("/approvals", json=upd, headers=mgr)
    assert (
        r2.status_code == 201 and r2.json()["status"] == "pending_owner"
    )  # manager langsung ke owner
    assert act(client, boss, r2.json()["id"], "approve").status_code == 200
    got = {
        x["id"]: x["data"]
        for x in pull(client, wh)["docs"]
        if x["collection"] == "suppliers"
    }
    assert got[sid]["name"] == "UD Sayur Segar" and got[sid]["phone"] == "0899"

    bad = {
        "type": "supplier",
        "supplier": {"action": "update", "supplier_id": "tidak-ada", "name": "X"},
    }
    assert client.post("/approvals", json=bad, headers=chef).status_code == 404


def test_po_submission_validation(client, db):
    prepare(client, db)
    wh, whb, mgr, boss = (
        auth_header(client, u) for u in ("wh", "wh_b", "mgr_a", "boss")
    )
    wid = me_id(client, wh)
    push(client, wh, [d("purchase_orders", "px", po("px", wid, supplier="tidak-ada"))])
    assert submit(client, wh, "px").status_code == 400  # supplier belum terdaftar
    push(client, wh, [d("purchase_orders", "pe", po("pe", wid, lines=[]))])
    assert submit(client, wh, "pe").status_code == 400  # tanpa item
    assert submit(client, wh, "tidak-ada").status_code == 404
    assert submit(client, mgr, "po1").status_code == 404  # bukan pembuat draf
    assert submit(client, whb, "po1").status_code == 404  # outlet lain
    aid = submit(client, wh).json()["id"]
    act(client, mgr, aid, "approve")
    act(client, boss, aid, "approve")
    assert submit(client, wh).status_code == 409  # sudah dipesan
