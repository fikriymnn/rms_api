from .test_sync import auth_header, d, ids, pull, push, world


def hold(hid, table="t1", **kw):
    data = {
        "id": hid,
        "tableId": table,
        "orderNumber": f"INV-{hid}",
        "createdAt": 1000,
        "releasedAt": None,
    }
    data.update(kw)
    return data


def test_table_holds_are_front_of_house_data_per_outlet(client, db):
    world(db)
    wa, ca, ka, wh, mgr_b = (
        auth_header(client, u) for u in ("wa", "ca", "ka", "wh", "mgr_b")
    )
    assert push(client, wa, [d("table_holds", "o1", hold("o1"))])[0]["status"] == "ok"
    assert (
        push(client, ca, [d("table_holds", "o2", hold("o2", "t2"))])[0]["status"]
        == "ok"
    )
    for h in (ka, wh):  # dapur dan gudang tidak membaca maupun menulis
        assert not any(c == "table_holds" for c, _ in ids(pull(client, h)))
        assert (
            push(client, h, [d("table_holds", "x", hold("x"))])[0]["reason"]
            == "forbidden"
        )
    assert not any(
        c == "table_holds" for c, _ in ids(pull(client, mgr_b))
    )  # outlet lain
    release = hold(
        "o1", releasedAt=2000
    )  # mengosongkan meja = pembaruan dokumen yang sama
    assert (
        push(client, ca, [d("table_holds", "o1", release, ts=2000)])[0]["status"]
        == "ok"
    )
