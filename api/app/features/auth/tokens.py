from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.security import hash_token

from .models import RefreshToken


def revoke_token(db: Session, raw_token: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw_token))
        .values(revoked=True)
    )
    db.commit()


def revoke_all(db: Session, user_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id, RefreshToken.revoked == False
        )  # noqa: E712
        .values(revoked=True)
    )
    db.commit()
