"""Data awal pajak & biaya layanan."""

import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.utils import new_id
from app.features.sync import service as sync_service
from app.features.sync.models import Doc


def seed_default_charges(db: Session) -> bool:
    """Bila belum ada data sama sekali: PB1 10% (sama dengan perilaku sebelum master data).

    Idempoten. Dokumen yang sudah dihapus juga dihitung, supaya PB1 yang sengaja
    dihapus owner tidak muncul lagi saat server restart.
    """
    if db.scalar(
        select(func.count()).select_from(Doc).where(Doc.collection == "charges")
    ):
        return False
    now = int(time.time() * 1000)
    cid = new_id()
    sync_service.lock_counter(db)
    sync_service.upsert_doc(
        db,
        "charges",
        cid,
        None,
        {
            "id": cid,
            "name": "PB1",
            "kind": "tax",
            "percent": 10,
            "onService": False,
            "active": True,
            "updatedAt": now,
        },
        now,
    )
    db.commit()
    return True
