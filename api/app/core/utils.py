import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Waktu UTC tanpa tzinfo (sesuai kolom DateTime MySQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
