from app.features.users.roles import Role

from .helpers import make_user
from .test_sync import auth_header, d, ids, pull, push, world


def test_manager_sees_only_own_outlet_finance_data(client, db):
    a, b = world(db)
    boss = auth_header(client, "boss")
    for o in (a, b):
        push(
            client,
            boss,
            [
                d(
                    "orders",
                    f"o_{o.name}",
                    {"id": f"o_{o.name}", "status": "paid", "items": []},
                ),
                d(
                    "expenses",
                    f"e_{o.name}",
                    {"id": f"e_{o.name}", "fromDrawer": False, "amount": 1},
                ),
                d("shifts", f"s_{o.name}", {"id": f"s_{o.name}", "cashierId": "x"}),
                d(
                    "stock_moves",
                    f"m_{o.name}",
                    {"id": f"m_{o.name}", "type": "waste", "qty": -1},
                ),
            ],
            outlet_id=o.id,
        )

    seen_a = {i for _, i in ids(pull(client, auth_header(client, "mgr_a")))}
    seen_b = {i for _, i in ids(pull(client, auth_header(client, "mgr_b")))}
    assert seen_a == {"o_A", "e_A", "s_A", "m_A"}
    assert seen_b == {"o_B", "e_B", "s_B", "m_B"}
    # owner bisa memilih outlet; manager tidak bisa memintanya
    assert {i for _, i in ids(pull(client, boss, outlet_id=b.id))} == seen_b
    assert (
        client.get(
            "/sync/pull",
            params={"outlet_id": b.id},
            headers=auth_header(client, "mgr_a"),
        ).status_code
        == 403
    )


def test_head_chef_and_warehouse_do_not_see_money_data(client, db):
    a, _ = world(db)
    make_user(db, "chef", Role.head_chef, a.id)
    boss = auth_header(client, "boss")
    push(
        client,
        boss,
        [
            d("expenses", "e1", {"id": "e1", "fromDrawer": False, "amount": 1}),
            d("shifts", "s1", {"id": "s1", "cashierId": "x"}),
            d("supplier_payments", "p1", {"id": "p1", "amount": 1}),
            d("orders", "o1", {"id": "o1", "status": "open", "items": []}),
        ],
        outlet_id=a.id,
    )
    chef = {c for c, _ in ids(pull(client, auth_header(client, "chef")))}
    assert "orders" in chef  # layar dapur butuh pesanan
    assert not ({"expenses", "shifts", "supplier_payments"} & chef)
    wh = {c for c, _ in ids(pull(client, auth_header(client, "wh")))}
    assert not ({"orders", "expenses", "shifts", "supplier_payments"} & wh)
