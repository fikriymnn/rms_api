from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import CurrentUser

from . import service
from .schemas import CollectionsOut, PullResponse, PushRequest, PushResponse

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/collections", response_model=CollectionsOut)
def list_collections(actor: CurrentUser):
    """Koleksi yang boleh dibaca/ditulis role ini (aplikasi hanya menyinkronkan yang boleh dibaca)."""
    return CollectionsOut(
        read=service.readable_collections(actor),
        write=service.writable_collections(actor),
    )


@router.get("/pull", response_model=PullResponse)
def pull(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    outlet_id: str | None = None,
    since: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
):
    return service.pull(db, actor, outlet_id, since, limit)


@router.post("/push", response_model=PushResponse)
def push(data: PushRequest, actor: CurrentUser, db: Session = Depends(get_db)):
    return PushResponse(results=service.push(db, actor, data.outlet_id, data.docs))
