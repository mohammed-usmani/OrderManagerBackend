"""Orders router: read + cancel (create/modify via agent only)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import get_current_user
from services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderItemResponse(BaseModel):
    id: str
    menu_item_id: str
    quantity: int
    price_at_order: float
    special_instructions: str | None

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: str
    status: str
    created_at: datetime
    confirmed_at: datetime | None
    paid_at: datetime | None
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


@router.get("", response_model=list[OrderResponse])
def list_orders(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return OrderService(db).get_orders(current_user.id)


@router.get("/current", response_model=OrderResponse)
def get_current_order(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = OrderService(db).get_or_create_cart(current_user.id)
    db.commit()
    return order


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        return OrderService(db).get_order(order_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{order_id}", status_code=204)
def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        service = OrderService(db)
        service.get_order(order_id, current_user.id)  # ownership check
        service.cancel_order(order_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
