from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import CurrentUser

from . import service
from .schemas import DeviceIn, NotificationOut, ReadIn, UnreadOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/devices", status_code=204)
def register_device(data: DeviceIn, actor: CurrentUser, db: Session = Depends(get_db)):
    service.register_device(db, actor, data.token, data.platform)


@router.post("/devices/unregister", status_code=204)
def unregister_device(
    data: DeviceIn, actor: CurrentUser, db: Session = Depends(get_db)
):
    service.unregister_device(db, actor, data.token)


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    before: int | None = None,
):
    return [
        NotificationOut(
            id=n.id,
            type=n.type,
            title=n.title,
            body=n.body,
            data=n.data,
            created_at=n.created_at,
            read=n.read_at is not None,
        )
        for n in service.list_for(db, actor, limit, before)
    ]


@router.get("/unread-count", response_model=UnreadOut)
def unread_count(actor: CurrentUser, db: Session = Depends(get_db)):
    return UnreadOut(count=service.unread_count(db, actor))


@router.post("/read", status_code=204)
def mark_read(data: ReadIn, actor: CurrentUser, db: Session = Depends(get_db)):
    service.mark_read(db, actor, data.ids, data.all, data.ref_type, data.ref_id)
