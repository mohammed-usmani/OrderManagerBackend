"""Menu router: public read + admin CRUD."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin
from services.menu_service import MenuService

router = APIRouter(prefix="/menu", tags=["menu"])


class MenuItemResponse(BaseModel):
    id: str
    name: str
    description: str | None
    how_its_made: str | None
    taste_profile: str | None
    category: str
    price: float
    currency: str
    serving: str | None
    dietary: list | None
    spice_level: str | None
    popularity: float | None
    popularity_note: str | None
    available: bool

    model_config = {"from_attributes": True}


class CreateMenuItemRequest(BaseModel):
    id: str
    name: str
    category: str
    price: float
    description: str | None = None
    how_its_made: str | None = None
    taste_profile: str | None = None
    currency: str = "INR"
    serving: str | None = None
    dietary: list | None = None
    spice_level: str | None = None
    popularity: float | None = None
    popularity_note: str | None = None
    available: bool = True


class UpdateMenuItemRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    available: bool | None = None
    spice_level: str | None = None
    serving: str | None = None


@router.get("", response_model=list[MenuItemResponse])
def list_menu(db: Session = Depends(get_db)):
    return MenuService(db).list_items(include_unavailable=False)


@router.get("/{item_id}", response_model=MenuItemResponse)
def get_menu_item(item_id: str, db: Session = Depends(get_db)):
    try:
        return MenuService(db).get_item(item_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("", response_model=MenuItemResponse, status_code=201)
def create_menu_item(
    req: CreateMenuItemRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    item = MenuService(db).create_item(**req.model_dump())
    db.commit()
    return item


@router.patch("/{item_id}", response_model=MenuItemResponse)
def update_menu_item(
    item_id: str,
    req: UpdateMenuItemRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        item = MenuService(db).update_item(item_id, **updates)
        db.commit()
        return item
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{item_id}", status_code=204)
def disable_menu_item(
    item_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        MenuService(db).disable_item(item_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
