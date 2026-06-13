"""Floors router: admin-only management of restaurant storeys."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin
from services.floor_service import FloorService

router = APIRouter(prefix="/floors", tags=["floors"])


class FloorResponse(BaseModel):
    id: str
    name: str
    display_order: int
    active: bool
    width: int
    height: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateFloorRequest(BaseModel):
    name: str
    display_order: int = 0
    active: bool = True
    width: int = 1000
    height: int = 640


class UpdateFloorRequest(BaseModel):
    name: str | None = None
    display_order: int | None = None
    active: bool | None = None
    width: int | None = None
    height: int | None = None


@router.get("", response_model=list[FloorResponse])
def list_floors(db: Session = Depends(get_db), _=Depends(require_admin)):
    return FloorService(db).list_floors()


@router.post("", response_model=FloorResponse, status_code=201)
def create_floor(
    req: CreateFloorRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    floor = FloorService(db).create_floor(**req.model_dump())
    db.commit()
    return floor


@router.patch("/{floor_id}", response_model=FloorResponse)
def update_floor(
    floor_id: str,
    req: UpdateFloorRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        floor = FloorService(db).update_floor(floor_id, **req.model_dump(exclude_unset=True))
        db.commit()
        return floor
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{floor_id}", status_code=204)
def delete_floor(floor_id: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    try:
        FloorService(db).delete_floor(floor_id)
        db.commit()
    except ValueError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))
