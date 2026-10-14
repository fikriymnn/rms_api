from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import CurrentUser, require_roles

from . import service
from .roles import Role
from .schemas import PasswordReset, UserCreate, UserOut, UserUpdate

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_roles(Role.owner, Role.manager))],
)


@router.get("", response_model=list[UserOut])
def list_users(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    outlet_id: str | None = None,
    role: Role | None = None,
    active: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return service.list_users_for(
        db,
        actor,
        outlet_id=outlet_id,
        role=role.value if role else None,
        active=active,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, actor: CurrentUser, db: Session = Depends(get_db)):
    return service.create_user_by(db, actor, data)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    return service.get_user_for(db, actor, user_id)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str, data: UserUpdate, actor: CurrentUser, db: Session = Depends(get_db)
):
    target = service.get_user_for(db, actor, user_id)
    return service.update_user_by(db, actor, target, data)


@router.post("/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: str, data: PasswordReset, actor: CurrentUser, db: Session = Depends(get_db)
):
    target = service.get_user_for(db, actor, user_id)
    service.reset_password_by(db, actor, target, data.new_password)


@router.post("/{user_id}/deactivate", response_model=UserOut)
def deactivate(user_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    target = service.get_user_for(db, actor, user_id)
    return service.set_active_by(db, actor, target, False)


@router.post("/{user_id}/activate", response_model=UserOut)
def activate(user_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    target = service.get_user_for(db, actor, user_id)
    return service.set_active_by(db, actor, target, True)
