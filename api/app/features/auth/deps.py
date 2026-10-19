from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.features.users.models import User
from app.features.users.roles import Role
from fastapi import Depends, HTTPException, Request

bearer = HTTPBearer(auto_error=False)


# endpoint yang masih boleh dipakai sebelum password sementara diganti
_ALLOWED_BEFORE_CHANGE = {"/auth/change-password", "/auth/me", "/auth/logout"}


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=401,
        detail="Belum login atau token tidak valid",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    user_id = decode_access_token(creds.credentials)
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.active:
        raise unauthorized
    if user.must_change_password and request.url.path not in _ALLOWED_BEFORE_CHANGE:
        raise HTTPException(
            status_code=403, detail="Anda harus mengganti password terlebih dahulu"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    allowed = {r.value for r in roles}

    def checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Tidak punya akses")
        return user

    return checker
