import pytest
from sqlalchemy import select

from app.core.config import settings
from app.features.notifications import fcm
from app.features.notifications import push as push_mod
from app.features.notifications.models import DeviceToken
from app.features.notifications.push import dispatch as real_dispatch
from app.features.users.roles import Role

from .conftest import TestingSession
from .helpers import make_user
from .test_approvals import act, prepare, submit
from .test_menu_workflow import proposal
from .test_purchasing_rules import me_id, po
from .test_purchasing_rules import setup as base_setup
from .test_sync import auth_header, d, push

USERS = ("boss", "mgr_a", "mgr_b", "ca", "wa", "ka", "wh", "chef", "wh_b")


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    """Tangkap push tanpa menghubungi FCM; pastikan FCM dianggap mati."""
    out: list[dict] = []
    monkeypatch.setattr(settings, "fcm_service_account_file", "")
    monkeypatch.setattr(push_mod, "dispatch", lambda items: out.extend(items))
    return out


def tok(u):
    return f"token-{u}-" + "x" * 24


def register_all(client, users=USERS):
    for u in users:
        r = client.post(
            "/notifications/devices",
            json={"token": tok(u)},
            headers=auth_header(client, u),
        )
        assert r.status_code == 204, r.text


def inbox(client, u):
    return client.get("/notifications", headers=auth_header(client, u)).json()


def tokens(sent):
    return {i["token"] for i in sent}


def test_device_token_ownership(client, db):
    base_setup(db)
    boss, mgr = auth_header(client, "boss"), auth_header(client, "mgr_a")
    t = tok("shared")
    assert (
        client.post(
            "/notifications/devices", json={"token": "pendek"}, headers=boss
        ).status_code
        == 422
    )
    assert client.post("/notifications/devices", json={"token": t}).status_code == 401
    assert (
        client.post(
            "/notifications/devices", json={"token": t}, headers=boss
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/notifications/devices", json={"token": t}, headers=mgr
        ).status_code
        == 204
    )  # dipakai akun lain
    rows = db.scalars(select(DeviceToken)).all()
    assert len(rows) == 1 and rows[0].user_id == me_id(client, mgr)
    client.post(
        "/notifications/devices/unregister", json={"token": t}, headers=boss
    )  # bukan pemilik
    db.rollback()
    assert len(db.scalars(select(DeviceToken)).all()) == 1
    client.post("/notifications/devices/unregister", json={"token": t}, headers=mgr)
    db.rollback()
    assert db.scalars(select(DeviceToken)).all() == []


def test_approval_notifications_are_targeted(client, db, sent):
    prepare(client, db)
    register_all(client)
    wh, mgr, boss = (auth_header(client, u) for u in ("wh", "mgr_a", "boss"))
    wid = me_id(client, wh)

    aid = submit(client, wh).json()["id"]
    assert tokens(sent) == {
        tok("mgr_a"),
        tok("chef"),
    }  # tingkat 1: manager dan head chef outlet A saja
    for u in USERS:
        assert len(inbox(client, u)) == (1 if u in ("mgr_a", "chef") else 0), u
    n = inbox(client, "mgr_a")[0]
    assert n["type"] == "approval" and n["data"]["id"] == aid and "Toko" in n["body"]

    sent.clear()
    act(client, mgr, aid, "approve")
    assert tokens(sent) == {tok("boss"), tok("wh")}  # owner dan pemohon
    sent.clear()
    act(client, boss, aid, "approve")
    assert tokens(sent) == {tok("wh")}
    assert "Pengajuan disetujui" in {x["title"] for x in inbox(client, "wh")}

    push(client, wh, [d("purchase_orders", "po2", po("po2", wid))])
    a2 = submit(client, wh, "po2").json()["id"]
    act(client, mgr, a2, "approve")
    sent.clear()
    act(client, boss, a2, "reject", "anggaran habis")
    assert tokens(sent) == {tok("wh")}
    rejected = [x for x in inbox(client, "wh") if x["title"] == "Pengajuan ditolak"]
    assert rejected and "anggaran habis" in rejected[0]["body"]

    push(client, mgr, [d("purchase_orders", "pm", po("pm", me_id(client, mgr)))])
    sent.clear()
    submit(client, mgr, "pm")
    assert tokens(sent) == {tok("boss")}  # manager langsung ke owner

    push(client, wh, [d("purchase_orders", "po3", po("po3", wid))])
    a3 = submit(client, wh, "po3").json()["id"]
    sent.clear()
    act(client, wh, a3, "withdraw")
    assert sent == []  # menarik pengajuan tidak mengirim apa pun


def test_order_notifications_go_to_kitchen_only(client, db, sent):
    a, b = base_setup(db)
    make_user(db, "kb", Role.kitchen, b.id)
    register_all(client, USERS + ("kb",))
    mgr, wa = auth_header(client, "mgr_a"), auth_header(client, "wa")
    push(client, mgr, [d("tables", "t1", {"id": "t1", "name": "5"})])
    sent.clear()

    def item(i, name, qty):
        return {
            "id": i,
            "menuItemId": f"m{i}",
            "name": name,
            "price": 1000,
            "qty": qty,
            "note": "",
        }

    order = {
        "id": "o1",
        "number": "INV-1",
        "status": "open",
        "type": "dineIn",
        "tableId": "t1",
        "items": [item("i1", "Nasi Goreng", 2), item("i2", "Es Teh", 1)],
    }
    assert push(client, wa, [d("orders", "o1", order)])[0]["status"] == "ok"
    assert tokens(sent) == {
        tok("ka"),
        tok("chef"),
    }  # kitchen dan head chef outlet A saja
    n = inbox(client, "ka")[0]
    assert (
        n["title"] == "Pesanan baru • Meja 5"
        and n["body"] == "2× Nasi Goreng, 1× Es Teh"
    )
    for u in ("kb", "ca", "wa", "mgr_a", "boss", "wh"):
        assert inbox(client, u) == [], u

    sent.clear()
    more = {
        **order,
        "items": [
            item("i1", "Nasi Goreng", 3),
            item("i2", "Es Teh", 1),
            item("i3", "Kopi", 1),
        ],
    }
    push(client, wa, [d("orders", "o1", more, ts=2000)])
    assert tokens(sent) == {tok("ka"), tok("chef")}
    bodies = {x["title"]: x["body"] for x in inbox(client, "ka")}
    assert (
        bodies["Tambahan pesanan • Meja 5"] == "1× Nasi Goreng, 1× Kopi"
    )  # hanya selisihnya

    sent.clear()
    push(
        client, wa, [d("orders", "o1", {**more, "status": "paid"}, ts=3000)]
    )  # dibayar: tidak ada item baru
    push(client, wa, [d("orders", "o1", more, ts=2000)])  # kiriman ulang (stale)
    assert sent == []
    take = {
        "id": "o2",
        "number": "INV-2",
        "status": "open",
        "type": "takeaway",
        "items": [item("i9", "Kopi", 1)],
    }
    push(client, wa, [d("orders", "o2", take)])
    assert any(x["title"] == "Pesanan baru • Takeaway" for x in inbox(client, "ka"))


def test_proposal_notifications(client, db, sent):
    base_setup(db)
    register_all(client)
    chef, boss = auth_header(client, "chef"), auth_header(client, "boss")
    cid, oid = me_id(client, chef), me_id(client, boss)
    push(client, chef, [d("menu_proposals", "p1", proposal("p1", submittedBy=cid))])
    assert tokens(sent) == {tok("boss")}
    assert inbox(client, "boss")[0]["title"] == "Usulan menu baru"

    sent.clear()
    approved = proposal(
        "p1", submittedBy=cid, status="approved", decidedBy=oid, finalPrice=275000
    )
    push(client, boss, [d("menu_proposals", "p1", approved, ts=2000)])
    assert tokens(sent) == {tok("chef")}
    assert "Wagyu Steak" in inbox(client, "chef")[0]["body"]

    push(client, chef, [d("menu_proposals", "p2", proposal("p2", submittedBy=cid))])
    sent.clear()
    rejected = proposal(
        "p2",
        submittedBy=cid,
        status="rejected",
        decidedBy=oid,
        decisionNote="terlalu mahal",
    )
    push(client, boss, [d("menu_proposals", "p2", rejected, ts=2000)])
    assert tokens(sent) == {tok("chef")}
    assert any("terlalu mahal" in x["body"] for x in inbox(client, "chef"))


def test_inbox_endpoints_are_per_user(client, db, sent):
    prepare(client, db)
    register_all(client)
    submit(client, auth_header(client, "wh"))
    mgr, chef = auth_header(client, "mgr_a"), auth_header(client, "chef")
    assert client.get("/notifications/unread-count", headers=mgr).json() == {"count": 1}
    nid = inbox(client, "mgr_a")[0]["id"]
    assert inbox(client, "mgr_a")[0]["read"] is False

    client.post(
        "/notifications/read", json={"ids": [nid]}, headers=chef
    )  # milik orang lain: diabaikan
    assert client.get("/notifications/unread-count", headers=mgr).json() == {"count": 1}
    assert (
        client.post("/notifications/read", json={"ids": [nid]}, headers=mgr).status_code
        == 204
    )
    assert client.get("/notifications/unread-count", headers=mgr).json() == {"count": 0}
    assert inbox(client, "mgr_a")[0]["read"] is True

    assert client.get("/notifications/unread-count", headers=chef).json() == {
        "count": 1
    }
    client.post("/notifications/read", json={"all": True}, headers=chef)
    assert client.get("/notifications/unread-count", headers=chef).json() == {
        "count": 0
    }


def test_tokens_removed_when_access_is_revoked(client, db):
    base_setup(db)
    register_all(client, ("ca", "wa"))
    mgr = auth_header(client, "mgr_a")
    ca_id, wa_id = me_id(client, auth_header(client, "ca")), me_id(
        client, auth_header(client, "wa")
    )
    assert (
        client.post(
            f"/users/{ca_id}/reset-password",
            json={"new_password": "sementara-123"},
            headers=mgr,
        ).status_code
        == 204
    )
    db.rollback()
    assert {t.user_id for t in db.scalars(select(DeviceToken))} == {wa_id}
    assert client.post(f"/users/{wa_id}/deactivate", headers=mgr).status_code in (
        200,
        204,
    )
    db.rollback()
    assert db.scalars(select(DeviceToken)).all() == []


def test_dead_tokens_are_dropped_after_failed_send(client, db, monkeypatch):
    base_setup(db)
    register_all(client, ("ca",))
    monkeypatch.setattr(push_mod, "SessionLocal", TestingSession)
    monkeypatch.setattr(push_mod.fcm, "send", lambda item: "invalid")
    push_mod._run(
        [
            {
                "token": tok("ca"),
                "title": "x",
                "body": "y",
                "channel": "approvals",
                "data": {},
            }
        ]
    )
    db.rollback()
    assert db.scalars(select(DeviceToken)).all() == []


def test_push_is_disabled_without_fcm_config():
    assert fcm.is_configured() is False
    real_dispatch(
        [{"token": "t", "title": "x", "body": "y", "channel": "approvals", "data": {}}]
    )  # tidak error


def test_mark_read_by_target(client, db, sent):
    base_setup(db)
    mgr, wa = auth_header(client, "mgr_a"), auth_header(client, "wa")
    ka, chef = auth_header(client, "ka"), auth_header(client, "chef")

    def order(oid):
        item = {
            "id": f"i-{oid}",
            "menuItemId": "m1",
            "name": "Kopi",
            "price": 1000,
            "qty": 1,
            "note": "",
        }
        return {
            "id": oid,
            "number": oid,
            "status": "open",
            "type": "takeaway",
            "items": [item],
        }

    push(client, wa, [d("orders", "o1", order("o1")), d("orders", "o2", order("o2"))])
    count = lambda h: client.get("/notifications/unread-count", headers=h).json()[
        "count"
    ]  # noqa: E731
    assert count(ka) == 2 and count(chef) == 2

    assert (
        client.post(
            "/notifications/read",
            json={"ref_type": "order", "ref_id": "o1"},
            headers=ka,
        ).status_code
        == 204
    )
    assert count(ka) == 1 and count(chef) == 2  # hanya milik sendiri, hanya o1
    client.post(
        "/notifications/read", json={"ref_id": "o2"}, headers=chef
    )  # tanpa ref_type: diabaikan
    assert count(chef) == 2
    client.post(
        "/notifications/read", json={"ref_type": "order"}, headers=ka
    )  # semua pesanan
    assert count(ka) == 0 and count(chef) == 2
    client.post(
        "/notifications/read", json={"ref_type": "approval"}, headers=chef
    )  # jenis lain: tidak terpengaruh
    assert count(chef) == 2
