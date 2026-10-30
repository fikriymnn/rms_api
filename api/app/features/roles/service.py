from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, object_session

from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.features.roles.catalog import (
    ALL_PERMISSIONS,
    OWNER_KEY,
    OWNER_PERMISSIONS,
    SYSTEM_DEFAULTS,
    SYSTEM_ROLES,
)
from app.features.roles.models import RoleDef, RolePermission
from app.features.roles.schemas import RoleCreate, RoleOut, RoleUpdate
from app.features.users.models import User

_CACHE = "role_perms"


def _invalidate(db: Session) -> None:
    db.info.pop(_CACHE, None)


# ---- pengecekan izin (dipakai di seluruh aplikasi) ---------------------------
def _load(db: Session, key: str) -> frozenset[str]:
    if key == OWNER_KEY:
        return OWNER_PERMISSIONS
    cache = db.info.setdefault(_CACHE, {})
    if key not in cache:
        if db.get(RoleDef, key) is None:  # belum di-seed: pakai bawaan
            perms = SYSTEM_DEFAULTS.get(key, frozenset())
        else:
            perms = frozenset(
                db.scalars(
                    select(RolePermission.permission).where(
                        RolePermission.role_key == key
                    )
                )
            )
        cache[key] = perms & ALL_PERMISSIONS  # buang izin usang
    return cache[key]


def permissions_of(user: User) -> frozenset[str]:
    if user.role == OWNER_KEY:
        return OWNER_PERMISSIONS
    db = object_session(user)
    if db is None:
        return SYSTEM_DEFAULTS.get(user.role, frozenset())
    return _load(db, user.role)


def has_any(user: User, perms) -> bool:
    return bool(permissions_of(user).intersection(perms))


def can(user: User, perm: str) -> bool:
    return perm in permissions_of(user)


def role_label(user: User) -> str:
    db = object_session(user)
    row = db.get(RoleDef, user.role) if db is not None else None
    if row:
        return row.name
    return SYSTEM_ROLES.get(user.role, (user.role,))[0]


# ---- lookup untuk notifikasi / kebijakan user --------------------------------
def role_keys_with(db: Session, perm: str) -> tuple[str, ...]:
    """Key semua role yang memegang `perm` (termasuk bawaan yang belum di-seed)."""
    keys = set(
        db.scalars(
            select(RolePermission.role_key).where(RolePermission.permission == perm)
        )
    )
    seeded = set(db.scalars(select(RoleDef.key)))
    for k, perms in SYSTEM_DEFAULTS.items():
        if k != OWNER_KEY and k not in seeded and perm in perms:
            keys.add(k)
    if perm in OWNER_PERMISSIONS:
        keys.add(OWNER_KEY)
    return tuple(sorted(keys))


def staff_keys(db: Session) -> set[str]:
    keys = set(db.scalars(select(RoleDef.key).where(RoleDef.is_staff.is_(True))))
    seeded = set(db.scalars(select(RoleDef.key)))
    keys |= {k for k, v in SYSTEM_ROLES.items() if v[2] and k not in seeded}
    return keys


def all_keys(db: Session) -> set[str]:
    return set(db.scalars(select(RoleDef.key))) | set(SYSTEM_ROLES)


def role_exists(db: Session, key: str) -> bool:
    return key in all_keys(db)


# ---- seed --------------------------------------------------------------------
def seed_system_roles(db: Session) -> None:
    """Idempoten: hanya membuat peran bawaan yang belum ada."""
    for key, (name, desc, staff) in SYSTEM_ROLES.items():
        if db.get(RoleDef, key) is not None:
            continue
        db.add(
            RoleDef(
                key=key, name=name, description=desc, is_system=True, is_staff=staff
            )
        )
        db.flush()
        if key != OWNER_KEY:
            db.add_all(
                RolePermission(role_key=key, permission=p)
                for p in sorted(SYSTEM_DEFAULTS[key])
            )
    db.commit()


# ---- CRUD --------------------------------------------------------------------
def _validate(perms: list[str]) -> set[str]:
    bad = sorted(set(perms) - ALL_PERMISSIONS)
    if bad:
        raise BadRequest(f"Izin tidak dikenal: {', '.join(bad)}")
    return set(perms)


def _out(role: RoleDef, perms: set[str] | frozenset[str], count: int) -> RoleOut:
    locked = role.key == OWNER_KEY
    return RoleOut(
        key=role.key,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        is_staff=role.is_staff,
        locked=locked,
        permissions=sorted(OWNER_PERMISSIONS if locked else perms),
        user_count=count,
    )


def _user_counts(db: Session) -> dict[str, int]:
    return dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())


def _perms_by_role(db: Session) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for k, p in db.execute(select(RolePermission.role_key, RolePermission.permission)):
        out.setdefault(k, set()).add(p)
    return out


def list_roles(db: Session) -> list[RoleOut]:
    counts, perms = _user_counts(db), _perms_by_role(db)
    roles = db.scalars(select(RoleDef).order_by(RoleDef.is_system.desc(), RoleDef.name))
    return [_out(r, perms.get(r.key, set()), counts.get(r.key, 0)) for r in roles]


def _get(db: Session, key: str) -> RoleDef:
    role = db.get(RoleDef, key)
    if role is None:
        raise NotFound("Role tidak ditemukan")
    return role


def get_role(db: Session, key: str) -> RoleOut:
    role = _get(db, key)
    perms = set(
        db.scalars(
            select(RolePermission.permission).where(RolePermission.role_key == key)
        )
    )
    count = (
        db.scalar(select(func.count()).select_from(User).where(User.role == key)) or 0
    )
    return _out(role, perms, count)


def _name_taken(db: Session, name: str, except_key: str | None = None) -> bool:
    stmt = select(RoleDef.key).where(func.lower(RoleDef.name) == name.strip().lower())
    if except_key:
        stmt = stmt.where(RoleDef.key != except_key)
    return db.scalar(stmt) is not None


def create_role(db: Session, data: RoleCreate) -> RoleOut:
    if db.get(RoleDef, data.key) is not None or data.key in SYSTEM_ROLES:
        raise Conflict("Key role sudah dipakai")
    if _name_taken(db, data.name):
        raise Conflict("Nama role sudah dipakai")
    perms = _validate(data.permissions)
    db.add(
        RoleDef(
            key=data.key,
            name=data.name.strip(),
            description=data.description,
            is_system=False,
            is_staff=data.is_staff,
        )
    )
    db.flush()
    db.add_all(RolePermission(role_key=data.key, permission=p) for p in sorted(perms))
    db.commit()
    _invalidate(db)
    return get_role(db, data.key)


def update_role(db: Session, key: str, data: RoleUpdate) -> RoleOut:
    role = _get(db, key)
    if key == OWNER_KEY:
        raise Forbidden("Role owner tidak bisa diubah")
    if data.name is not None:
        if _name_taken(db, data.name, except_key=key):
            raise Conflict("Nama role sudah dipakai")
        role.name = data.name.strip()
    if data.description is not None:
        role.description = data.description
    if data.is_staff is not None:
        role.is_staff = data.is_staff
    if data.permissions is not None:
        perms = _validate(data.permissions)
        db.execute(delete(RolePermission).where(RolePermission.role_key == key))
        db.add_all(RolePermission(role_key=key, permission=p) for p in sorted(perms))
    db.commit()
    _invalidate(db)
    return get_role(db, key)


def reset_role(db: Session, key: str) -> RoleOut:
    role = _get(db, key)
    if not role.is_system or key == OWNER_KEY:
        raise Forbidden("Hanya peran bawaan (selain owner) yang bisa dikembalikan")
    name, desc, staff = SYSTEM_ROLES[key]
    role.name, role.description, role.is_staff = name, desc, staff
    db.execute(delete(RolePermission).where(RolePermission.role_key == key))
    db.add_all(
        RolePermission(role_key=key, permission=p) for p in sorted(SYSTEM_DEFAULTS[key])
    )
    db.commit()
    _invalidate(db)
    return get_role(db, key)


def delete_role(db: Session, key: str) -> None:
    role = _get(db, key)
    if role.is_system:
        raise Forbidden("Peran bawaan tidak bisa dihapus")
    used = (
        db.scalar(select(func.count()).select_from(User).where(User.role == key)) or 0
    )
    if used:
        raise Conflict(
            f"Role masih dipakai {used} pengguna. Pindahkan dulu penggunanya."
        )
    db.delete(role)
    db.commit()
    _invalidate(db)
