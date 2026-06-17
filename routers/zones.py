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
    floor_id: str | None
    name: str
    is_ac: bool
    display_order: int
    active: bool
    pos_x: int
    pos_y: int
    width: int
    height: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateZoneRequest(BaseModel):
    name: str
    floor_id: str | None = None
    is_ac: bool = False
    display_order: int = 0
    active: bool = True
    pos_x: int | None = None
    pos_y: int | None = None
    width: int | None = None
    height: int | None = None


class UpdateZoneRequest(BaseModel):
    name: str | None = None
    floor_id: str | None = None
    is_ac: bool | None = None
    display_order: int | None = None
    active: bool | None = None
    pos_x: int | None = None
    pos_y: int | None = None
    width: int | None = None
    height: int | None = None


class ZonePosition(BaseModel):
    zone_id: str
    pos_x: int | None = None
    pos_y: int | None = None
    width: int | None = None
    height: int | None = None


class SaveZonePositionsRequest(BaseModel):
    zones: list[ZonePosition]


@router.get("", response_model=list[ZoneResponse])
def list_zones(db: Session = Depends(get_db), _=Depends(require_admin)):
    return ZoneService(db).list_zones()


@router.post("", response_model=ZoneResponse, status_code=201)
def create_zone(
    req: CreateZoneRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    # exclude_none so omitted geometry falls back to the model's defaults
    # (the columns are NOT NULL).
    try:
        zone = ZoneService(db).create_zone(**req.model_dump(exclude_none=True))
        db.commit()
        return zone
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/positions")
def save_zone_positions(
    req: SaveZonePositionsRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Bulk-save zone rectangles after drag/resize in the floor-plan builder."""
    updated = ZoneService(db).save_positions([z.model_dump() for z in req.zones])
    db.commit()
    return {"updated": updated}


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
