"""Payments router: Razorpay (test) checkout + verify + webhook, and cash settle.

Razorpay endpoints are public so a dine-in guest can pay from their own phone
without a login: the amount is computed server-side and verify is protected by
an unforgeable signature. Guests may add a tip, but only cashiers can apply a
discount. Cash settlement is staff-only (cashier/manager).
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import RAZORPAY_KEY_ID
from db.base import get_db
from db.models.payment import Payment
from dependencies import get_optional_user, require_roles
from services.payment_service import PaymentService
from services.payments import razorpay_enabled, verify_webhook_signature
from services.roles import CASHIER_ROLES

router = APIRouter(prefix="/payments", tags=["payments"])

_require_cashier = require_roles(CASHIER_ROLES)


class Target(BaseModel):
    order_id: str | None = None
    session_id: str | None = None
    tip: float = 0
    discount: float = 0
    discount_reason: str | None = None


def _check_discount(req: Target, user) -> None:
    if req.discount and getattr(user, "role", None) not in CASHIER_ROLES:
        raise HTTPException(status_code=403, detail="Only staff can apply a discount")


class ConfirmRequest(BaseModel):
    provider_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.get("/config")
def payment_config():
    """Public: lets the UI decide whether to offer online payment."""
    return {"razorpay_enabled": razorpay_enabled(), "key_id": RAZORPAY_KEY_ID}


@router.post("/quote")
def quote(req: Target, db: Session = Depends(get_db), user=Depends(get_optional_user)):
    _check_discount(req, user)
    try:
        return {"amount_due": PaymentService(db).amount_due(
            order_id=req.order_id, session_id=req.session_id, tip=req.tip, discount=req.discount)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/razorpay/order")
def create_razorpay_checkout(req: Target, db: Session = Depends(get_db), user=Depends(get_optional_user)):
    _check_discount(req, user)
    if not razorpay_enabled():
        raise HTTPException(status_code=503, detail="Online payment isn't configured.")
    try:
        out = PaymentService(db).create_checkout(
            order_id=req.order_id, session_id=req.session_id, tip=req.tip, discount=req.discount,
            discount_reason=req.discount_reason)
        db.commit()
        return out
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Razorpay error: {e}")


@router.post("/razorpay/verify")
def verify_razorpay(req: ConfirmRequest, db: Session = Depends(get_db)):
    try:
        pay = PaymentService(db).confirm_razorpay(
            provider_order_id=req.provider_order_id,
            razorpay_payment_id=req.razorpay_payment_id,
            signature=req.razorpay_signature,
        )
        db.commit()
        return {"status": pay.status, "amount": float(pay.amount)}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """Razorpay → us on payment.captured. Idempotent; verified by webhook secret."""
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    try:
        event = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")
    if event.get("event") == "payment.captured":
        entity = event.get("payload", {}).get("payment", {}).get("entity", {})
        provider_order_id = entity.get("order_id")
        payment_id = entity.get("id")
        if provider_order_id:
            pay = db.query(Payment).filter(Payment.provider_order_id == provider_order_id).first()
            if pay and pay.status != "paid":
                # Signature already verified the source; finalize via the service.
                PaymentService(db).confirm_razorpay(
                    provider_order_id=provider_order_id,
                    razorpay_payment_id=payment_id or pay.provider_payment_id or "",
                    signature=_self_sign(provider_order_id, payment_id or ""),
                )
                db.commit()
    return {"ok": True}


def _self_sign(order_id: str, payment_id: str) -> str:
    """Re-sign so the webhook path can reuse confirm_razorpay's verification
    (the webhook itself was already verified with the webhook secret)."""
    import hashlib
    import hmac
    from config import RAZORPAY_KEY_SECRET
    return hmac.new(
        RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


@router.post("/cash")
def settle_cash(req: Target, db: Session = Depends(get_db), actor=Depends(_require_cashier)):
    try:
        pay = PaymentService(db).settle_cash(
            order_id=req.order_id, session_id=req.session_id,
            tip=req.tip, discount=req.discount, discount_reason=req.discount_reason, actor=actor)
        db.commit()
        return {"status": pay.status, "amount": float(pay.amount), "method": "cash"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
