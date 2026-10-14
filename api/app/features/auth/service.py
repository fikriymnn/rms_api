from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.core.utils import utcnow
from app.features.users import service as users_service
from app.features.users.models import User
from app.features.users.schemas import UserOut

from .models import RefreshToken
from .schemas import AccessOut, LoginResponse
from .tokens import revoke_all, revoke_token  # noqa: F401


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = users_service.get_by_username(db, username)
    if user is None:
        verify_password(DUMMY_HASH, password)  # samakan waktu proses
        return None
    if not verify_password(user.password_hash, password) or not user.active:
        return None
    return user


def issue_tokens(db: Session, user: User) -> LoginResponse:
    access, ttl = create_access_token(user.id)
    raw = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )
    db.commit()
    return LoginResponse(
        access_token=access,
        refresh_token=raw,
        expires_in=ttl,
        user=UserOut.model_validate(user),
    )


def refresh_access(db: Session, raw_token: str) -> AccessOut | None:
    rt = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    if rt is None or rt.revoked or rt.expires_at < utcnow():
        return None
    user = db.get(User, rt.user_id)
    if user is None or not user.active:
        return None
    access, ttl = create_access_token(user.id)
    return AccessOut(access_token=access, expires_in=ttl)
