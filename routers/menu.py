"""Menu router: public read + admin CRUD."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin
from services.image_service import upload_enabled, upload_image
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
    image_url: str | None
    available: bool
    track_stock: bool = False
    stock_qty: int | None = None
    is_86: bool = False
    hsn_code: str | None = None

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
    image_url: str | None = None
    available: bool = True
    track_stock: bool = False
    stock_qty: int | None = None
    hsn_code: str | None = None


class UpdateMenuItemRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    how_its_made: str | None = None
    taste_profile: str | None = None
    category: str | None = None
    price: float | None = None
    currency: str | None = None
    serving: str | None = None
    dietary: list | None = None
    spice_level: str | None = None
    popularity: float | None = None
    popularity_note: str | None = None
    image_url: str | None = None
    available: bool | None = None
    track_stock: bool | None = None
    stock_qty: int | None = None
    is_86: bool | None = None
    hsn_code: str | None = None


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


class UploadImageResponse(BaseModel):
    image_url: str


@router.post("/upload-image", response_model=UploadImageResponse)
async def upload_menu_image(
    file: UploadFile = File(...),
    _=Depends(require_admin),
):
    """Upload a menu-item image to Cloudinary; returns the hosted URL to store
    in the item's image_url. Falls back with a clear error if upload isn't
    configured (admin can paste a URL instead)."""
    if not upload_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image upload isn't configured (CLOUDINARY_URL unset). Paste an image URL instead.",
        )
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")
    try:
        contents = await file.read()
        url = upload_image(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload failed: {e}")
    return UploadImageResponse(image_url=url)


class ReembedResponse(BaseModel):
    embedded: int


@router.post("/reembed", response_model=ReembedResponse)
def reembed_menu(
    only_missing: bool = False,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Regenerate semantic-search embeddings for the menu (admin tool)."""
    count = MenuService(db).reembed_all(only_missing=only_missing)
    db.commit()
    return ReembedResponse(embedded=count)
