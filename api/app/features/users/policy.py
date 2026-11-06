from sqlalchemy.orm import object_session

from app.features.roles import service as roles
from app.features.roles.catalog import OWNER_KEY

from .models import User


def can_view(actor: User, target: User) -> bool:
    if actor.id == target.id or actor.role == OWNER_KEY:
        return True
    if roles.can(actor, "users.read"):
        return target.outlet_id is not None and target.outlet_id == actor.outlet_id
    return False


def can_manage(actor: User, target: User) -> bool:
    """Cakupan saja. Izin aksinya (users.update dst.) dijaga di router."""
    if actor.id == target.id:  # akun sendiri diubah lewat /auth
        return False
    if target.role == OWNER_KEY:  # owner tidak bisa dikelola lewat API
        return False
    if actor.role == OWNER_KEY:
        return True
    db = object_session(actor)
    return target.outlet_id == actor.outlet_id and target.role in roles.staff_keys(db)


def creatable_roles(actor: User) -> set[str]:
    """Role yang boleh dibuat/diberikan oleh actor."""
    db = object_session(actor)
    if actor.role == OWNER_KEY:
        return roles.all_keys(db) - {OWNER_KEY}
    if roles.can(actor, "users.create") or roles.can(actor, "users.update"):
        return roles.staff_keys(db)
    return set()
