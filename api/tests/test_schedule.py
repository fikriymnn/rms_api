from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.features.attendance import schedule
from app.features.attendance import service as attendance_service
from app.features.outlets.models import OutletHours
from app.features.users.roles import Role

from .helpers import auth_header, make_user
from .test_attendance import clock, geo_outlet
from .test_roles import new_role

WIB = ZoneInfo("Asia/Jakarta")


def wib(h, m=0, day=2):
    """Senin 2 Nov 2026 (WIB) secara bawaan, dalam epoch ms."""
    return int(datetime(2026, 11, day, h, m, tzinfo=WIB).timestamp() * 1000)


NOW = wib(23, 0)  # jam server dikunci: Senin 23:00 WIB


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(attendance_service, "now_ms", lambda: NOW)


def week(open_="08:00", close="22:00", closed=()):
    return [
        (
            {"weekday": d, "closed": True}
            if d in closed
            else {"weekday": d, "closed": False, "open": open_, "close": close}
        )
        for d in range(7)
    ]


def body(days=None, lead=30, tail=15, grace=5, tz="Asia/Jakarta"):
    return {
        "timezone": tz,
        "lead_min": lead,
        "tail_min": tail,
        "grace_min": grace,
        "days": days if days is not None else week(),
    }


def put(client, h, outlet, payload):
    return client.put(f"/attendance/schedule/{outlet.id}", json=payload, headers=h)


def setup(db, client):
    a = geo_outlet(db, "A")
    b = geo_outlet(db, "B")
    make_user(db, "boss", Role.owner)
    for u in ("u1", "u2", "u3", "u4"):
        make_user(db, u, Role.cashier, a.id)
    return a, b, auth_header(client, "boss")


def test_schedule_defaults_and_validation(client, db):
    a, b, boss = setup(db, client)
    r = client.get(f"/attendance/schedule/{a.id}", headers=boss)
    assert r.status_code == 200
    j = r.json()
    assert j["timezone"] == "Asia/Jakarta" and j["grace_min"] == 5
    assert [d["configured"] for d in j["days"]] == [False] * 7

    r = put(client, boss, a, body(week(closed=(6,))))
    assert r.status_code == 200, r.text
    days = r.json()["days"]
    assert days[0] == {
        "weekday": 0,
        "configured": True,
        "closed": False,
        "open": "08:00",
        "close": "22:00",
    }
    assert days[6]["closed"] is True and days[6]["open"] is None
    assert r.json()["lead_min"] == 30 and r.json()["tail_min"] == 15

    dup = week() + [{"weekday": 0, "closed": False, "open": "09:00", "close": "21:00"}]
    assert (
        put(client, boss, a, body(dup[:7] + dup[7:])).status_code == 422
    )  # lebih dari 7 hari
    two = [week()[0], week()[0]]
    assert put(client, boss, a, body(two)).status_code == 400  # hari dobel
    assert put(client, boss, a, body(week("08:00", "08:00"))).status_code == 400  # sama
    assert (
        put(client, boss, a, body([{"weekday": 0, "open": "08:00"}])).status_code == 400
    )
    assert put(client, boss, a, body(tz="Mars/Olympus")).status_code == 400
    assert (
        put(client, boss, a, body(week("8:00", "22:00"))).status_code == 422
    )  # format
    assert client.get("/attendance/schedule/tidak-ada", headers=boss).status_code == 404


def test_schedule_permission_and_outlet_scope(client, db):
    a, b, boss = setup(db, client)
    make_user(db, "mgr", Role.manager, a.id)
    assert (
        client.get(
            f"/attendance/schedule/{a.id}", headers=auth_header(client, "mgr")
        ).status_code
        == 403
    )
    assert new_role(client, boss, "jadwal", ["attendance.schedule"]).status_code == 201
    db.rollback()  # REPEATABLE READ: lihat role yang baru dibuat lewat API
    make_user(db, "sj", "jadwal", a.id)
    h = auth_header(client, "sj")
    assert put(client, h, a, body()).status_code == 200
    assert put(client, h, b, body()).status_code == 403  # outlet lain


def test_on_time_late_early_and_overtime(client, db):
    a, b, boss = setup(db, client)
    assert (
        put(client, boss, a, body()).status_code == 200
    )  # sched_in 07:30, sched_out 22:15, grace 5
    h = {u: auth_header(client, u) for u in ("u1", "u2", "u3", "u4")}

    ins = {
        "u1": (wib(7, 20), "on_time", 0),  # sebelum jadwal
        "u2": (wib(7, 45), "late", 15),
        "u3": (wib(7, 36), "late", 6),  # 6 menit > toleransi 5
        "u4": (wib(7, 34), "on_time", 0),  # 4 menit, dalam toleransi
    }
    for u, (ts, status, mins) in ins.items():
        r = clock(client, h[u], "in", ts=ts)
        assert r.status_code == 200, r.text
        j = r.json()
        assert (j["in_status"], j["late_min"]) == (status, mins), u
        assert j["sched_in_at"] == wib(7, 30) and j["sched_out_at"] == wib(22, 15)
        assert j["out_status"] is None  # belum pulang

    outs = {
        "u1": (wib(22, 20), "on_time", 0, 0),  # +5 menit, dalam toleransi
        "u2": (wib(21, 30), "early", 45, 0),
        "u3": (wib(22, 50), "overtime", 0, 35),
        "u4": (wib(22, 10), "on_time", 0, 0),  # -5 menit
    }
    rec = {}
    for u, (ts, status, early, over) in outs.items():
        r = clock(client, h[u], "out", ts=ts)
        assert r.status_code == 200, r.text
        j = r.json()
        rec[u] = j["id"]
        assert (j["out_status"], j["early_out_min"], j["overtime_min"]) == (
            status,
            early,
            over,
        ), u

    rows = {
        s["user_name"]: s
        for s in client.get(
            f"/attendance/summary?outlet_id={a.id}", headers=boss
        ).json()
    }
    assert (rows["U1"]["late_count"], rows["U1"]["overtime_minutes"]) == (0, 0)
    assert (
        rows["U2"]["late_count"],
        rows["U2"]["late_minutes"],
        rows["U2"]["early_out_count"],
    ) == (1, 15, 1)
    assert (
        rows["U3"]["late_count"],
        rows["U3"]["late_minutes"],
        rows["U3"]["overtime_minutes"],
    ) == (1, 6, 35)

    # koreksi jam pulang u2 menjadi 22:10 -> tepat waktu
    r = client.patch(
        f"/attendance/{rec['u2']}",
        json={"clock_out_at": wib(22, 10), "reason": "salah tekan"},
        headers=boss,
    )
    assert r.status_code == 200, r.text
    assert r.json()["out_status"] == "on_time" and r.json()["early_out_min"] == 0
    # koreksi jam masuk u2 menjadi 07:30 -> tidak terlambat lagi
    r = client.patch(
        f"/attendance/{rec['u2']}",
        json={"clock_in_at": wib(7, 30), "reason": "lupa absen"},
        headers=boss,
    )
    assert r.json()["in_status"] == "on_time" and r.json()["late_min"] == 0


def test_schedule_snapshot_is_not_rewritten_by_later_changes(client, db):
    a, b, boss = setup(db, client)
    put(client, boss, a, body())
    r = clock(client, auth_header(client, "u1"), "in", ts=wib(7, 20))
    rid = r.json()["id"]
    put(client, boss, a, body(week("12:00", "20:00"), lead=0))  # jadwal berubah
    got = [
        x
        for x in client.get(f"/attendance?outlet_id={a.id}", headers=boss).json()
        if x["id"] == rid
    ][0]
    assert got["sched_in_at"] == wib(7, 30) and got["in_status"] == "on_time"


def test_closed_day_and_outlet_without_schedule_are_not_judged(client, db):
    a, b, boss = setup(db, client)
    c = geo_outlet(db, "C")
    make_user(db, "ub", Role.cashier, b.id)
    make_user(db, "uc", Role.cashier, c.id)
    assert (
        put(client, boss, b, body(week(closed=(0,)))).status_code == 200
    )  # Senin libur
    for u in ("ub", "uc"):  # B: libur hari itu, C: belum punya jadwal
        j = clock(client, auth_header(client, u), "in", ts=wib(9, 0)).json()
        assert (
            j["in_status"] is None and j["sched_in_at"] is None and j["late_min"] == 0
        )


def test_overnight_close_and_timezone(db):
    o = geo_outlet(db, "N")
    db.add(
        OutletHours(
            outlet_id=o.id, weekday=0, closed=False, open_min=18 * 60, close_min=2 * 60
        )
    )
    db.commit()
    o.staff_lead_min = o.staff_tail_min = 0
    exp = schedule.expected_for(db, o, wib(19, 0))
    assert exp.sched_in == wib(18, 0) and exp.sched_out == wib(
        2, 0, day=3
    )  # tutup 02:00 esok hari
    o.timezone = "Asia/Makassar"  # WITA = WIB + 1 jam: 18:00 WITA = 17:00 WIB
    exp = schedule.expected_for(db, o, wib(19, 0))
    assert exp.sched_in == wib(17, 0)
