import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import delete

from app.core.database import SessionLocal

from . import fcm
from .models import DeviceToken

log = logging.getLogger("rms.push")
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="push")

PushItem = dict[str, Any]  # token, title, body, channel, data


def dispatch(items: list[PushItem]) -> None:
    """Kirim di latar belakang agar permintaan pengguna tidak menunggu FCM."""
    if not items or not fcm.is_configured():
        return
    _pool.submit(_run, items)


def _run(items: list[PushItem]) -> None:
    dead: list[str] = []
    for item in items:
        try:
            if fcm.send(item) == "invalid":
                dead.append(item["token"])
        except Exception:
            log.exception("push gagal")
    if dead:
        with SessionLocal() as db:
            db.execute(delete(DeviceToken).where(DeviceToken.token.in_(dead)))
            db.commit()
