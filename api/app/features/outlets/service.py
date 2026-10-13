from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Outlet
from .schemas import OutletCreate, OutletUpdate

_NOT_NULLABLE = {"name", "address", "radius_m", "active"}


def list_outlets(db: Session) -> list[Outlet]:
    return list(db.scalars(select(Outlet).order_by(Outlet.name)).all())


def get_outlet(db: Session, outlet_id: str) -> Outlet | None:
    return db.get(Outlet, outlet_id)


def create_outlet(db: Session, data: OutletCreate) -> Outlet:
    outlet = Outlet(**data.model_dump())
    db.add(outlet)
    db.commit()
    db.refresh(outlet)
    return outlet


def update_outlet(db: Session, outlet: Outlet, data: OutletUpdate) -> Outlet:
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key in _NOT_NULLABLE:
            continue
        setattr(outlet, key, value)
    db.commit()
    db.refresh(outlet)
    return outlet
