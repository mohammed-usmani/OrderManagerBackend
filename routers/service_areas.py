"""Service-areas router: admin-only management of the delivery allowlist."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin
from services.service_area_service import ServiceAreaService

router = APIRouter(prefix="/service-areas", tags=["service-areas"])


class ServiceAreaResponse(BaseModel):
    id: str
    name: str
    pincode: str | None
    aliases: list | None
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateServiceAreaRequest(BaseModel):
    name: str
    pincode: str | None = None
    aliases: list | None = None
    active: bool = True


class UpdateServiceAreaRequest(BaseModel):
    name: str | None = None
    pincode: str | None = None
    aliases: list | None = None
    active: bool | None = None


@router.get("", response_model=list[ServiceAreaResponse])
def list_service_areas(
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    return ServiceAreaService(db).list_areas()


@router.post("", response_model=ServiceAreaResponse, status_code=201)
def create_service_area(
    req: CreateServiceAreaRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    area = ServiceAreaService(db).create_area(**req.model_dump())
    db.commit()
    return area


@router.patch("/{area_id}", response_model=ServiceAreaResponse)
def update_service_area(
    area_id: str,
    req: UpdateServiceAreaRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        area = ServiceAreaService(db).update_area(
            area_id, **req.model_dump(exclude_unset=True)
        )
        db.commit()
        return area
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{area_id}", status_code=204)
def delete_service_area(
    area_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        ServiceAreaService(db).delete_area(area_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
