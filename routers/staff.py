"""Staff router: owner/manager provisioning of staff accounts + roles."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_roles
from services.roles import OWNER_ROLES, STAFF_ROLES
from services.user_service import UserService, MIN_PASSWORD_LEN

router = APIRouter(prefix="/staff", tags=["staff"])

# Only owners/managers manage staff.
_require_manager = require_roles(OWNER_ROLES)


class StaffResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateStaffRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str


class UpdateStaffRequest(BaseModel):
    role: str


def _validate_role(role: str) -> None:
    if role not in STAFF_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {sorted(STAFF_ROLES)}",
        )


@router.get("", response_model=list[StaffResponse])
def list_staff(db: Session = Depends(get_db), _=Depends(_require_manager)):
    return UserService(db).list_staff()


@router.post("", response_model=StaffResponse, status_code=201)
def create_staff(
    req: CreateStaffRequest,
    db: Session = Depends(get_db),
    _=Depends(_require_manager),
):
    _validate_role(req.role)
    if len(req.password or "") < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if not req.name.strip():
        raise HTTPException(400, "Name is required")
    try:
        user = UserService(db).register(
            req.email.strip().lower(), req.password, req.name.strip(), role=req.role
        )
        db.commit()
        return user
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{user_id}", response_model=StaffResponse)
def update_staff(
    user_id: str,
    req: UpdateStaffRequest,
    db: Session = Depends(get_db),
    actor=Depends(_require_manager),
):
    _validate_role(req.role)
    # Don't let someone demote themselves out of management and lock the panel.
    if user_id == actor.id and req.role not in OWNER_ROLES:
        raise HTTPException(400, "You can't remove your own management access")
    try:
        user = UserService(db).set_role(user_id, req.role)
        db.commit()
        return user
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_staff(
    user_id: str,
    db: Session = Depends(get_db),
    actor=Depends(_require_manager),
):
    if user_id == actor.id:
        raise HTTPException(400, "You can't delete your own account")
    try:
        UserService(db).delete(user_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
