import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

_ph = PasswordHasher()
# dipakai agar waktu respons sama untuk username yang tidak ada
DUMMY_HASH = _ph.hash("dummy-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: str) -> tuple[str, int]:
    ttl = settings.access_token_minutes * 60
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    token = jwt.encode(
        {"sub": user_id, "exp": exp, "typ": "access"},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, ttl


def decode_access_token(token: str) -> str | None:
    """Kembalikan user_id, atau None jika token tidak valid/kedaluwarsa."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload.get("sub")


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
