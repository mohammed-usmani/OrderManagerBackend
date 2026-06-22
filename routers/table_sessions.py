"""Table-sessions router: view a dine-in running tab and settle the table."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_roles
from services.order_service import OrderService
from services.roles import CASHIER_ROLES, STAFF_ROLES
from services.table_service import TableService

router = APIRouter(prefix="/table-sessions", tags=["table-sessions"])

# Any staff can view a tab; only cashiers/managers/owners can settle (take money).
_require_staff = require_roles(STAFF_ROLES)
_require_cashier = require_roles(CASHIER_ROLES)


@router.get("/{session_id}")
def get_session_detail(
    session_id: str,
    db: Session = Depends(get_db),
    _=Depends(_require_staff),
):
    """The full running tab (every round + combined check) for a table session."""
    try:
        return TableService(db).session_detail(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{session_id}/settle")
def settle_session(
    session_id: str,
    db: Session = Depends(get_db),
    _=Depends(_require_cashier),
):
    """Settle the check: pay every fired round, close the session, free the table."""
    try:
        OrderService(db).settle_table_session(session_id)
        db.commit()
        return TableService(db).session_detail(session_id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))


class TransferRequest(BaseModel):
    to_table_id: str


class MergeRequest(BaseModel):
    into_session_id: str


@router.post("/{session_id}/transfer")
def transfer_session(
    session_id: str,
    req: TransferRequest,
    db: Session = Depends(get_db),
    actor=Depends(_require_cashier),
):
    """Move an open tab (all its orders) to a different table."""
    try:
        OrderService(db).transfer_session(session_id, req.to_table_id, actor)
        db.commit()
        return TableService(db).session_detail(session_id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{session_id}/merge")
def merge_session(
    session_id: str,
    req: MergeRequest,
    db: Session = Depends(get_db),
    actor=Depends(_require_cashier),
):
    """Merge this tab into another open tab (combine checks); frees this table."""
    try:
        OrderService(db).merge_sessions(session_id, req.into_session_id, actor)
        db.commit()
        return TableService(db).session_detail(req.into_session_id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
