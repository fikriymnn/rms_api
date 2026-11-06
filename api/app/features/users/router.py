from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import CurrentUser, require_perm
from app.features.roles import service as roles_service

from . import policy, service
from .schemas import PasswordReset, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/role-options", dependencies=[Depends(require_perm("users.read"))])
def role_options(actor: CurrentUser, db: Session = Depends(get_db)) -> list[dict]:
    """Semua role (untuk label) + apakah actor boleh memberikannya (untuk dropdown)."""
    allowed = policy.creatable_roles(actor)
    return [
        {"key": r.key, "name": r.name, "assignable": r.key in allowed}
        for r in roles_service.list_roles(db)
    ]


@router.get(
    "", response_model=list[UserOut], dependencies=[Depends(require_perm("users.read"))]
)
def list_users(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    outlet_id: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return service.list_users_for(
        db,
        actor,
        outlet_id=outlet_id,
        role=role,
        active=active,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_perm("users.create"))],
)
def create_user(data: UserCreate, actor: CurrentUser, db: Session = Depends(get_db)):
    return service.create_user_by(db, actor, data)


@router.get(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_perm("users.read"))],
)
def get_user(user_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    return service.get_user_for(db, actor, user_id)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_perm("users.update"))],
)
def update_user(
    user_id: str, data: UserUpdate, actor: CurrentUser, db: Session = Depends(get_db)
):
    target = service.get_user_for(db, actor, user_id)
    return service.update_user_by(db, actor, target, data)


@router.post(
    "/{user_id}/reset-password",
    status_code=204,
    dependencies=[Depends(require_perm("users.reset_password"))],
)
def reset_password(
    user_id: str, data: PasswordReset, actor: CurrentUser, db: Session = Depends(get_db)
):
    target = service.get_user_for(db, actor, user_id)
    service.reset_password_by(db, actor, target, data.new_password)


@router.post(
    "/{user_id}/deactivate",
    response_model=UserOut,
    dependencies=[Depends(require_perm("users.set_active"))],
)
def deactivate(user_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    target = service.get_user_for(db, actor, user_id)
    return service.set_active_by(db, actor, target, False)


@router.post(
    "/{user_id}/activate",
    response_model=UserOut,
    dependencies=[Depends(require_perm("users.set_active"))],
)
def activate(user_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    target = service.get_user_for(db, actor, user_id)
    return service.set_active_by(db, actor, target, True)
