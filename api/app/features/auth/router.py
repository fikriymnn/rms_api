from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.features.users.schemas import UserOut
from .tokens import revoke_all, revoke_token  # noqa: F401

from . import service, throttle
from .deps import CurrentUser
from .schemas import (
    AccessOut,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "-"
    key = f"{data.username.strip().lower()}|{ip}"
    if throttle.is_blocked(key):
        raise HTTPException(
            429, "Terlalu banyak percobaan. Coba lagi beberapa menit lagi."
        )
    user = service.authenticate(db, data.username, data.password)
    if user is None:
        throttle.fail(key)
        raise HTTPException(401, "Username atau password salah")
    throttle.reset(key)
    return service.issue_tokens(db, user)


@router.post("/refresh", response_model=AccessOut)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    out = service.refresh_access(db, data.refresh_token)
    if out is None:
        raise HTTPException(401, "Refresh token tidak valid")
    return out


@router.post("/logout", status_code=204)
def logout(data: RefreshRequest, db: Session = Depends(get_db)):
    service.revoke_token(db, data.refresh_token)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.post("/change-password", status_code=204)
def change_password(
    data: ChangePasswordRequest, user: CurrentUser, db: Session = Depends(get_db)
):
    if not verify_password(user.password_hash, data.old_password):
        raise HTTPException(400, "Password lama salah")
    user.password_hash = hash_password(data.new_password)
    service.revoke_all(
        db, user.id
    )  # sekaligus commit; semua perangkat harus login ulang
