"""Settings router: admin-editable bill charge policy."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin
from services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


class ChargeRule(BaseModel):
    key: str
    label: str
    rate: float
    applies_to: str  # all | dine_in | parcel
    ac_only: bool = False


class ChargePolicyResponse(BaseModel):
    charges: list[ChargeRule]


class UpdateChargePolicyRequest(BaseModel):
    charges: list[ChargeRule]


@router.get("/charge-policy", response_model=ChargePolicyResponse)
def get_charge_policy(db: Session = Depends(get_db), _=Depends(require_admin)):
    return ChargePolicyResponse(charges=SettingsService(db).get_charge_policy())


@router.put("/charge-policy", response_model=ChargePolicyResponse)
def update_charge_policy(
    req: UpdateChargePolicyRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        saved = SettingsService(db).set_charge_policy(
            [c.model_dump() for c in req.charges]
        )
        db.commit()
        return ChargePolicyResponse(charges=saved)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
