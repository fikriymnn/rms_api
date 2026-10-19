from app.features.outlets.models import Outlet
from app.features.users import service as users_service
from app.features.users.roles import Role
import time
from app.core.config import settings

PASSWORD = "rahasia123"


def make_outlet(db, name="Outlet Uji"):
    o = Outlet(name=name)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def make_user(
    db, username, role=Role.cashier, outlet_id=None, active=True, consent=True
):
    u = users_service.create_user(
        db,
        username=username,
        password=PASSWORD,
        name=username.title(),
        role=role,
        outlet_id=outlet_id,
    )
    if not active:
        u.active = False
    if consent:
        u.attendance_consent_version = settings.attendance_consent_version
        u.attendance_consent_at = int(time.time() * 1000)
    db.commit()
    return u


def login(client, username, password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def auth_header(client, username):
    r = login(client, username)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
