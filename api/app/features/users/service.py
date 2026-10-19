from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.security import hash_password
from app.features.auth.tokens import revoke_all
from app.features.outlets import service as outlet_service

from . import policy
from .models import User
from .roles import Role
from .schemas import UserCreate, UserUpdate


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username.strip().lower()))


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    name: str,
    role: Role,
    outlet_id: str | None = None,
    position: str = "",
    must_change_password: bool = False,
) -> User:
    """Tanpa pemeriksaan hak akses: dipakai CLI dan service di bawah ini."""
    username = username.strip().lower()
    if get_by_username(db, username):
        raise Conflict("Username sudah dipakai")
    if role == Role.owner:
        outlet_id = None  # owner tidak terikat outlet
    else:
        outlet = outlet_service.get_outlet(db, outlet_id) if outlet_id else None
        if outlet is None or not outlet.active:
            raise BadRequest("Outlet wajib diisi, harus ada, dan masih aktif")
    user = User(
        username=username,
        password_hash=hash_password(password),
        name=name,
        position=position,
        role=role.value,
        outlet_id=outlet_id,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---- operasi dengan pemeriksaan hak akses (dipakai router) ----


def get_user_for(db: Session, actor: User, user_id: str) -> User:
    target = db.get(User, user_id)
    if target is None or not policy.can_view(actor, target):
        raise NotFound(
            "User tidak ditemukan"
        )  # 404, bukan 403: tidak membocorkan keberadaan
    return target


def list_users_for(
    db: Session,
    actor: User,
    *,
    outlet_id: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[User]:
    stmt = select(User)
    if actor.role == Role.manager.value:
        if outlet_id is not None and outlet_id != actor.outlet_id:
            raise Forbidden("Anda hanya boleh melihat user di outlet Anda")
        stmt = stmt.where(User.outlet_id == actor.outlet_id)
    elif outlet_id is not None:
        stmt = stmt.where(User.outlet_id == outlet_id)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if active is not None:
        stmt = stmt.where(User.active == active)
    stmt = stmt.order_by(User.name).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def create_user_by(db: Session, actor: User, data: UserCreate) -> User:
    if data.role.value not in policy.creatable_roles(actor):
        raise Forbidden("Anda tidak boleh membuat user dengan role ini")
    if actor.role == Role.manager.value:
        if data.outlet_id not in (None, actor.outlet_id):
            raise Forbidden("Manager hanya boleh menambah user di outletnya sendiri")
        outlet_id = actor.outlet_id
    else:
        outlet_id = data.outlet_id
    return create_user(
        db,
        username=data.username,
        password=data.password,
        name=data.name,
        role=data.role,
        outlet_id=outlet_id,
        position=data.position,
        must_change_password=True,  # password awal dibuat admin: wajib diganti
    )


def update_user_by(db: Session, actor: User, target: User, data: UserUpdate) -> User:
    if not policy.can_manage(actor, target):
        raise Forbidden("Anda tidak boleh mengubah user ini")
    changes = data.model_dump(exclude_unset=True)

    new_role = changes.get("role")
    if new_role is not None:
        if new_role.value not in policy.creatable_roles(actor):
            raise Forbidden("Anda tidak boleh memberikan role ini")
        target.role = new_role.value

    new_outlet = changes.get("outlet_id")
    if new_outlet is not None:
        if actor.role != Role.owner.value:
            raise Forbidden("Hanya owner yang boleh memindahkan user ke outlet lain")
        outlet = outlet_service.get_outlet(db, new_outlet)
        if outlet is None or not outlet.active:
            raise BadRequest("Outlet tidak ditemukan atau nonaktif")
        target.outlet_id = new_outlet

    for key in ("name", "position"):
        if changes.get(key) is not None:
            setattr(target, key, changes[key])
    db.commit()
    db.refresh(target)
    return target


def reset_password_by(
    db: Session, actor: User, target: User, new_password: str
) -> None:
    if not policy.can_manage(actor, target):
        raise Forbidden("Anda tidak boleh mereset password user ini")
    target.password_hash = hash_password(new_password)
    target.must_change_password = True  # password sementara
    db.commit()
    revoke_all(db, target.id)  # semua perangkat harus login ulang


def set_active_by(db: Session, actor: User, target: User, active: bool) -> User:
    if not policy.can_manage(actor, target):
        raise Forbidden("Anda tidak boleh mengubah status user ini")
    target.active = active
    db.commit()
    if not active:
        revoke_all(db, target.id)
    db.refresh(target)
    return target
