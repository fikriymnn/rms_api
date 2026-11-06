from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import require_roles
from app.features.users.roles import Role

from . import service
from .schemas import OutletCreate, OutletOut, OutletUpdate

# semua endpoint di router ini hanya untuk owner
router = APIRouter(
    prefix="/outlets",
    tags=["outlets"],
    dependencies=[Depends(require_roles(Role.owner))],
)


@router.get("", response_model=list[OutletOut])
def list_outlets(db: Session = Depends(get_db)):
    return service.list_outlets(db)


@router.post("", response_model=OutletOut, status_code=status.HTTP_201_CREATED)
def create_outlet(data: OutletCreate, db: Session = Depends(get_db)):
    return service.create_outlet(db, data)


@router.get("/{outlet_id}", response_model=OutletOut)
def get_outlet(outlet_id: str, db: Session = Depends(get_db)):
    outlet = service.get_outlet(db, outlet_id)
    if outlet is None:
        raise HTTPException(status_code=404, detail="Outlet tidak ditemukan")
    return outlet


@router.patch("/{outlet_id}", response_model=OutletOut)
def update_outlet(outlet_id: str, data: OutletUpdate, db: Session = Depends(get_db)):
    outlet = service.get_outlet(db, outlet_id)
    if outlet is None:
        raise HTTPException(status_code=404, detail="Outlet tidak ditemukan")
    return service.update_outlet(db, outlet, data)
