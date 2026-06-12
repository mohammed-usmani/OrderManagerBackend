"""Zones router: admin-only management of dining rooms/sections."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin
from services.zone_service import ZoneService

router = APIRouter(prefix="/zones", tags=["zones"])


class ZoneResponse(BaseModel):
    id: str
    name: str
    is_ac: bool
    display_order: int
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateZoneRequest(BaseModel):
    name: str
    is_ac: bool = False
    display_order: int = 0
    active: bool = True


class UpdateZoneRequest(BaseModel):
    name: str | None = None
    is_ac: bool | None = None
    display_order: int | None = None
    active: bool | None = None


@router.get("", response_model=list[ZoneResponse])
def list_zones(db: Session = Depends(get_db), _=Depends(require_admin)):
    return ZoneService(db).list_zones()


@router.post("", response_model=ZoneResponse, status_code=201)
def create_zone(
    req: CreateZoneRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    zone = ZoneService(db).create_zone(**req.model_dump())
    db.commit()
    return zone


@router.patch("/{zone_id}", response_model=ZoneResponse)
def update_zone(
    zone_id: str,
    req: UpdateZoneRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        zone = ZoneService(db).update_zone(zone_id, **req.model_dump(exclude_unset=True))
        db.commit()
        return zone
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{zone_id}", status_code=204)
def delete_zone(zone_id: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    try:
        ZoneService(db).delete_zone(zone_id)
        db.commit()
    except ValueError as e:
        # 404 for missing; 409 for "still has tables".
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))
