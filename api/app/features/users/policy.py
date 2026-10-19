from .models import User
from .roles import STAFF_ROLES, Role

STAFF_VALUES = {r.value for r in STAFF_ROLES}


def can_view(actor: User, target: User) -> bool:
    if actor.id == target.id or actor.role == Role.owner.value:
        return True
    if actor.role == Role.manager.value:
        return target.outlet_id is not None and target.outlet_id == actor.outlet_id
    return False


def can_manage(actor: User, target: User) -> bool:
    if actor.id == target.id:  # akun sendiri diubah lewat /auth
        return False
    if target.role == Role.owner.value:  # owner tidak bisa dikelola lewat API
        return False
    if actor.role == Role.owner.value:
        return True
    if actor.role == Role.manager.value:
        return target.outlet_id == actor.outlet_id and target.role in STAFF_VALUES
    return False


def creatable_roles(actor: User) -> set[str]:
    """Role yang boleh dibuat/diberikan oleh actor."""
    if actor.role == Role.owner.value:
        return {Role.manager.value, Role.head_chef.value} | STAFF_VALUES
    if actor.role == Role.manager.value:
        return set(STAFF_VALUES)
    return set()
