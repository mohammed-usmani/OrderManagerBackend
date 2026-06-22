"""Tables router: admin table management, the live floor map, and the public
QR-resolution endpoint the dine-in ordering app uses to bind a call to a table.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin, require_roles
from services.roles import STAFF_ROLES
from services.table_service import TableService

# The live floor map is read by waiters/cashiers/managers, not just admins.
_require_staff = require_roles(STAFF_ROLES)

router = APIRouter(prefix="/tables", tags=["tables"])


class TableResponse(BaseModel):
    id: str
    zone_id: str
    label: str
    seats: int
    pos_x: int | None
    pos_y: int | None
    shape: str
    qr_token: str
    status: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateTableRequest(BaseModel):
    zone_id: str
    label: str
    seats: int = 2
    pos_x: int | None = None
    pos_y: int | None = None
    shape: str = "round"
    active: bool = True


class UpdateTableRequest(BaseModel):
    zone_id: str | None = None
    label: str | None = None
    seats: int | None = None
    pos_x: int | None = None
    pos_y: int | None = None
    shape: str | None = None
    status: str | None = None
    active: bool | None = None


class TablePosition(BaseModel):
    table_id: str
    pos_x: int | None = None
    pos_y: int | None = None
    shape: str | None = None
    zone_id: str | None = None


class SavePositionsRequest(BaseModel):
    tables: list[TablePosition]


class ResolveTableResponse(BaseModel):
    table_id: str
    label: str
    seats: int
    zone_id: str | None
    zone_name: str | None
    is_ac: bool
    floor_id: str | None
    floor_name: str | None


# --- Public: resolve a scanned QR token (no auth — it's how diners start) ---

@router.get("/resolve/{qr_token}", response_model=ResolveTableResponse)
def resolve_table(qr_token: str, db: Session = Depends(get_db)):
    try:
        return TableService(db).resolve_qr(qr_token)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Admin: live floor map ---

@router.get("/floor")
def floor_map(db: Session = Depends(get_db), _=Depends(_require_staff)):
    return TableService(db).floor_map()


# --- Admin: CRUD ---

@router.get("", response_model=list[TableResponse])
def list_tables(
    zone_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    return TableService(db).list_tables(zone_id=zone_id)


@router.post("", response_model=TableResponse, status_code=201)
def create_table(
    req: CreateTableRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        table = TableService(db).create_table(**req.model_dump())
        db.commit()
        return table
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Bulk layout save — declared before /{table_id} so "positions" isn't captured
# as a table id.
@router.patch("/positions")
def save_positions(
    req: SavePositionsRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        updated = TableService(db).save_positions([t.model_dump() for t in req.tables])
        db.commit()
        return {"updated": updated}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{table_id}", response_model=TableResponse)
def update_table(
    table_id: str,
    req: UpdateTableRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        table = TableService(db).update_table(
            table_id, **req.model_dump(exclude_unset=True)
        )
        db.commit()
        return table
    except ValueError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/{table_id}", status_code=204)
def delete_table(table_id: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    try:
        TableService(db).delete_table(table_id)
        db.commit()
    except ValueError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))
