from app.features.charges.seed import seed_default_charges

from .test_approvals import act
from .test_sync import auth_header, d, pull, push, world


def charge(id_, name="PB1", kind="tax", percent=10, on_service=False, active=True):
    return {
        "id": id_,
        "name": name,
        "kind": kind,
        "percent": percent,
        "onService": on_service,
        "active": active,
    }


def seen(client, h):
    return {x["id"]: x for x in pull(client, h)["docs"] if x["collection"] == "charges"}


def request(client, h, **c):
    return client.post("/approvals", json={"type": "charge", "charge": c}, headers=h)


def test_owner_writes_directly_and_selling_roles_read(client, db):
    world(db)
    boss = auth_header(client, "boss")
    assert push(client, boss, [d("charges", "c1", charge("c1"))])[0]["status"] == "ok"
    assert (
        push(client, boss, [d("charges", "c1", charge("c1", percent=11), ts=2000)])[0][
            "status"
        ]
        == "ok"
    )
    for u in ("boss", "mgr_a", "mgr_b", "ca", "wa"):
        got = seen(client, auth_header(client, u))
        assert got["c1"]["data"]["percent"] == 11, u
    for u in ("ka", "wh"):  # dapur dan gudang tidak perlu tarif
        assert seen(client, auth_header(client, u)) == {}, u


def test_non_owner_cannot_write_charges_through_sync(client, db):
    world(db)
    for u in ("mgr_a", "ca", "wa", "ka", "wh"):
        r = push(client, auth_header(client, u), [d("charges", "x", charge("x"))])[0]
        assert r["status"] == "rejected", u
    assert seen(client, auth_header(client, "boss")) == {}


def test_owner_writes_are_validated(client, db):
    world(db)
    boss = auth_header(client, "boss")
    bad = [
        charge("b1", percent=101),
        charge("b2", percent=-1),
        charge("b3", kind="lainnya"),
        charge("b4", name="  "),
        charge("b5", percent="10"),
    ]
    for i, c in enumerate(bad):
        assert (
            push(client, boss, [d("charges", c["id"], c)])[0]["status"] == "rejected"
        ), i
    assert (
        push(
            client,
            boss,
            [d("charges", "ok1", charge("ok1", "Service", "service", 5.5))],
        )[0]["status"]
        == "ok"
    )


def test_manager_create_needs_owner_approval(client, db):
    world(db)
    boss, mgr, ca = (auth_header(client, u) for u in ("boss", "mgr_a", "ca"))
    r = request(client, mgr, action="create", name="Service", kind="service", percent=5)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending_owner"  # manager langsung ke owner
    assert body["title"] == "Biaya baru: Service 5%"
    assert seen(client, ca) == {}  # belum berlaku sebelum disetujui
    assert act(client, boss, body["id"], "approve").status_code == 200
    got = list(seen(client, ca).values())
    assert len(got) == 1
    assert got[0]["data"]["name"] == "Service" and got[0]["data"]["percent"] == 5
    assert got[0]["data"]["kind"] == "service"


def test_manager_update_and_delete_follow_approval(client, db):
    world(db)
    boss, mgr, ca = (auth_header(client, u) for u in ("boss", "mgr_a", "ca"))
    push(client, boss, [d("charges", "c1", charge("c1"))])

    r = request(
        client, mgr, action="update", charge_id="c1", name="PB1", kind="tax", percent=12
    )
    assert r.status_code == 201, r.text
    assert r.json()["payload"]["before"]["percent"] == 10
    assert seen(client, ca)["c1"]["data"]["percent"] == 10  # belum berubah
    assert act(client, boss, r.json()["id"], "approve").status_code == 200
    assert seen(client, ca)["c1"]["data"]["percent"] == 12

    r = request(client, mgr, action="delete", charge_id="c1")
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Biaya hapus: PB1 12%"
    assert seen(client, ca)["c1"]["deleted"] is False
    assert act(client, boss, r.json()["id"], "approve").status_code == 200
    assert seen(client, ca)["c1"]["deleted"] is True


def test_rejected_request_changes_nothing(client, db):
    world(db)
    boss, mgr, ca = (auth_header(client, u) for u in ("boss", "mgr_a", "ca"))
    push(client, boss, [d("charges", "c1", charge("c1"))])
    r = request(client, mgr, action="delete", charge_id="c1")
    assert (
        act(client, boss, r.json()["id"], "reject", "tidak setuju").status_code == 200
    )
    assert seen(client, ca)["c1"]["deleted"] is False


def test_request_rules(client, db):
    world(db)
    boss, mgr = auth_header(client, "boss"), auth_header(client, "mgr_a")
    push(client, boss, [d("charges", "c1", charge("c1"))])
    new = dict(action="create", name="Service", kind="service", percent=5)
    assert request(client, boss, **new).status_code == 403  # owner menulis langsung
    for u in ("wh", "ca", "wa"):  # tanpa izin mengajukan perubahan biaya
        assert request(client, auth_header(client, u), **new).status_code == 403, u
    assert (
        request(client, mgr, action="create", name="pb1", percent=3).status_code == 409
    )  # nama sama
    assert (
        request(client, mgr, action="update", charge_id="nope", name="X").status_code
        == 404
    )
    assert request(client, mgr, action="create", name="   ").status_code == 400
    assert (
        request(client, mgr, action="create", name="Z", percent=101).status_code == 422
    )
    assert request(client, mgr, **new).status_code == 201
    assert request(client, mgr, **new).status_code == 409  # sudah ada pengajuan serupa


def test_approval_fails_cleanly_when_data_changed_meanwhile(client, db):
    world(db)
    boss, mgr = auth_header(client, "boss"), auth_header(client, "mgr_a")
    push(client, boss, [d("charges", "c1", charge("c1"))])
    r = request(client, mgr, action="update", charge_id="c1", name="PB1", percent=8)
    # owner menghapus biaya itu sebelum pengajuan diputuskan
    push(client, boss, [d("charges", "c1", charge("c1"), ts=5000, deleted=True)])
    assert act(client, boss, r.json()["id"], "approve").status_code == 409


def test_default_pb1_seed_is_idempotent_and_respects_deletion(client, db):
    world(db)
    assert seed_default_charges(db) is True
    assert seed_default_charges(db) is False
    db.rollback()
    rows = list(seen(client, auth_header(client, "ca")).values())
    assert len(rows) == 1
    assert (
        rows[0]["data"]["name"],
        rows[0]["data"]["percent"],
        rows[0]["data"]["kind"],
    ) == ("PB1", 10, "tax")
    # PB1 yang sengaja dihapus owner tidak dibuat ulang saat server restart
    cid = rows[0]["id"]
    push(
        client,
        auth_header(client, "boss"),
        [d("charges", cid, rows[0]["data"], ts=9_999_999_999_999, deleted=True)],
    )
    db.rollback()
    assert seed_default_charges(db) is False
