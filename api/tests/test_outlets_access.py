from app.features.users.roles import Role

from .helpers import PASSWORD, auth_header, login, make_user


def test_login_success(client, db):
    make_user(db, "budi", Role.owner)
    r = login(client, "budi")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "owner"
    assert "password_hash" not in body["user"]


def test_login_wrong_password(client, db):
    make_user(db, "budi", Role.owner)
    assert login(client, "budi", "salah-banget").status_code == 401


def test_login_unknown_user(client):
    assert login(client, "tidak-ada").status_code == 401


def test_inactive_user_cannot_login(client, db):
    make_user(db, "nonaktif", Role.owner, active=False)
    assert login(client, "nonaktif").status_code == 401


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_returns_profile(client, db):
    make_user(db, "sari", Role.owner)
    r = client.get("/auth/me", headers=auth_header(client, "sari"))
    assert r.status_code == 200
    assert r.json()["username"] == "sari"


def test_refresh_and_logout(client, db):
    make_user(db, "sari", Role.owner)
    rt = login(client, "sari").json()["refresh_token"]
    r = client.post("/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.post("/auth/logout", json={"refresh_token": rt}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": rt}).status_code == 401


def test_deactivated_user_token_stops_working(client, db):
    user = make_user(db, "rina", Role.owner)
    headers = auth_header(client, "rina")
    assert client.get("/auth/me", headers=headers).status_code == 200
    user.active = False
    db.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_change_password_revokes_refresh_tokens(client, db):
    make_user(db, "rina", Role.owner)
    tokens = login(client, "rina").json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = client.post(
        "/auth/change-password",
        json={"old_password": PASSWORD, "new_password": "baru-12345"},
        headers=headers,
    )
    assert r.status_code == 204
    assert (
        client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )
    assert login(client, "rina", "baru-12345").status_code == 200


def test_login_throttle(client, db):
    make_user(db, "ani", Role.owner)
    for _ in range(5):
        assert login(client, "ani", "salah").status_code == 401
    assert login(client, "ani").status_code == 429  # terkunci sementara
