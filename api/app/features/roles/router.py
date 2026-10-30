from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.auth.deps import require_roles
from app.features.roles import service
from app.features.roles.catalog import catalog_json
from app.features.roles.schemas import RoleCreate, RoleOut, RoleUpdate
from app.features.users.roles import Role

# Master role HANYA untuk owner. Sengaja tidak bisa didelegasikan: siapa pun yang
# boleh mengubah izin bisa memberi dirinya akses apa saja.
router = APIRouter(
    prefix="/roles", tags=["roles"], dependencies=[Depends(require_roles(Role.owner))]
)
DB = Annotated[Session, Depends(get_db)]


@router.get("/catalog")
def catalog() -> list[dict]:
    return catalog_json()


@router.get("", response_model=list[RoleOut])
def list_roles(db: DB):
    return service.list_roles(db)


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(data: RoleCreate, db: DB):
    return service.create_role(db, data)


@router.get("/{key}", response_model=RoleOut)
def get_role(key: str, db: DB):
    return service.get_role(db, key)


@router.patch("/{key}", response_model=RoleOut)
def update_role(key: str, data: RoleUpdate, db: DB):
    return service.update_role(db, key, data)


@router.post("/{key}/reset", response_model=RoleOut)
def reset_role(key: str, db: DB):
    return service.reset_role(db, key)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(key: str, db: DB):
    service.delete_role(db, key)
