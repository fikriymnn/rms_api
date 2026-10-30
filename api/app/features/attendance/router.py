from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import CurrentUser, require_perm
from app.features.users.models import User

from . import photos, service
from .schemas import (
    AttendanceOut,
    ConsentIn,
    ConsentOut,
    CorrectionIn,
    MeOut,
    ReviewIn,
    RevokeOut,
    SummaryRow,
)

router = APIRouter(prefix="/attendance", tags=["attendance"])
read_all = Depends(require_perm("attendance.read_all"))
correct = Depends(require_perm("attendance.correct"))
review = Depends(require_perm("attendance.review"))


def _name(db: Session, user_id: str) -> str:
    u = db.get(User, user_id)
    return u.name if u else "-"


@router.post(
    "/clock",
    response_model=AttendanceOut,
    dependencies=[Depends(require_perm("attendance.clock"))],
)
def clock(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    event_id: str = Form(min_length=8, max_length=36),
    kind: Literal["in", "out"] = Form(),
    client_time: int = Form(gt=0),
    lat: float = Form(ge=-90, le=90),
    lng: float = Form(ge=-180, le=180),
    accuracy_m: float = Form(ge=0, le=100000),
    mocked: bool = Form(False),
    liveness_ok: bool = Form(),
    photo: UploadFile = File(),
):
    raw = photo.file.read(photos.MAX_UPLOAD + 1)
    rec = service.clock(
        db,
        actor,
        event_id=event_id,
        kind=kind,
        client_time=client_time,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        mocked=mocked,
        liveness_ok=liveness_ok,
        photo_raw=raw,
    )
    return service.to_out(rec, actor.name)


@router.get("/me", response_model=MeOut)
def my_attendance(actor: CurrentUser, db: Session = Depends(get_db)):
    return service.me(db, actor)


@router.get("/summary", response_model=list[SummaryRow], dependencies=[read_all])
def summary(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    outlet_id: str | None = None,
    since: int | None = None,
    until: int | None = None,
):
    return service.summary(db, actor, outlet_id=outlet_id, since=since, until=until)


@router.get("", response_model=list[AttendanceOut], dependencies=[read_all])
def list_attendance(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    outlet_id: str | None = None,
    user_id: str | None = None,
    since: int | None = None,
    until: int | None = None,
    review_status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return service.list_records(
        db,
        actor,
        outlet_id=outlet_id,
        user_id=user_id,
        since=since,
        until=until,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )


@router.get("/{record_id}/photo/{kind}")
def get_photo(
    record_id: str,
    kind: Literal["in", "out"],
    actor: CurrentUser,
    db: Session = Depends(get_db),
):
    path = service.photo_file(db, actor, record_id, kind)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.patch("/{record_id}", response_model=AttendanceOut, dependencies=[correct])
def correct_record(
    record_id: str,
    data: CorrectionIn,
    actor: CurrentUser,
    db: Session = Depends(get_db),
):
    rec = service.get_record_for(db, actor, record_id)
    rec = service.correct(
        db,
        actor,
        rec,
        clock_in_at=data.clock_in_at,
        clock_out_at=data.clock_out_at,
        reason=data.reason,
    )
    return service.to_out(rec, _name(db, rec.user_id))


@router.patch(
    "/{record_id}/review", response_model=AttendanceOut, dependencies=[review]
)
def review_record(
    record_id: str, data: ReviewIn, actor: CurrentUser, db: Session = Depends(get_db)
):
    rec = service.get_record_for(db, actor, record_id)
    rec = service.review(db, actor, rec, data.status, data.note)
    return service.to_out(rec, _name(db, rec.user_id))


@router.post("/consent", response_model=ConsentOut)
def give_consent(data: ConsentIn, actor: CurrentUser, db: Session = Depends(get_db)):
    return service.give_consent(db, actor, data.version)


@router.post("/consent/revoke", response_model=RevokeOut)
def revoke_consent(actor: CurrentUser, db: Session = Depends(get_db)):
    return service.revoke_consent(db, actor)
