from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import CurrentUser

from . import service
from .schemas import ApprovalCounts, ApprovalCreate, ApprovalOut, DecisionIn, RejectIn

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED)
def create(data: ApprovalCreate, actor: CurrentUser, db: Session = Depends(get_db)):
    req = service.create(db, actor, data)
    return service.to_out(db, actor, [req])[0]


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    actor: CurrentUser,
    db: Session = Depends(get_db),
    scope: Literal["inbox", "mine", "history", "pending"] = "inbox",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return service.to_out(db, actor, service.list_for(db, actor, scope, limit, offset))


@router.get("/counts", response_model=ApprovalCounts)
def counts(actor: CurrentUser, db: Session = Depends(get_db)):
    return service.counts(db, actor)


@router.get("/{approval_id}", response_model=ApprovalOut)
def detail(approval_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    return service.to_out(db, actor, [service.get_for(db, actor, approval_id)])[0]


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
def approve(
    approval_id: str,
    data: DecisionIn,
    actor: CurrentUser,
    db: Session = Depends(get_db),
):
    return service.to_out(
        db, actor, [service.approve(db, actor, approval_id, data.note.strip())]
    )[0]


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
def reject(
    approval_id: str, data: RejectIn, actor: CurrentUser, db: Session = Depends(get_db)
):
    return service.to_out(
        db, actor, [service.reject(db, actor, approval_id, data.note.strip())]
    )[0]


@router.post("/{approval_id}/withdraw", response_model=ApprovalOut)
def withdraw(approval_id: str, actor: CurrentUser, db: Session = Depends(get_db)):
    return service.to_out(db, actor, [service.withdraw(db, actor, approval_id)])[0]
