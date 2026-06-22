"""Orders router: read + cancel (create/modify via agent only)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import get_current_user
from services.billing import bill_for_order
from services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderItemResponse(BaseModel):
    id: str
    menu_item_id: str
    quantity: int
    price_at_order: float
    special_instructions: str | None

    model_config = {"from_attributes": True}


class BillCharge(BaseModel):
    label: str
    rate: float
    amount: float


class OrderResponse(BaseModel):
    id: str
    status: str
    order_type: str
    created_at: datetime
    confirmed_at: datetime | None
    paid_at: datetime | None
    items: list[OrderItemResponse]
    subtotal: float
    charges: list[BillCharge]
    total: float


def _serialize(order) -> OrderResponse:
    items = [OrderItemResponse.model_validate(i) for i in order.items]
    # Use the bill frozen at confirm time (snapshot) so a confirmed/paid order's
    # total never drifts when the charge policy changes; falls back to a live,
    # context-aware computation for carts.
    bill = bill_for_order(order)
    return OrderResponse(
        id=order.id,
        status=order.status,
        order_type=order.order_type or "parcel",
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        paid_at=order.paid_at,
        items=items,
        subtotal=bill["subtotal"],
        charges=[BillCharge(**c) for c in bill["charges"]],
        total=bill["total"],
    )


@router.get("", response_model=list[OrderResponse])
def list_orders(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return [_serialize(o) for o in OrderService(db).get_orders(current_user.id)]


@router.get("/current", response_model=OrderResponse)
def get_current_order(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = OrderService(db).get_or_create_cart(current_user.id)
    db.commit()
    return _serialize(order)


class AddItemRequest(BaseModel):
    item_id: str
    quantity: int = 1
    special_instructions: str | None = None


@router.post("/current/items", response_model=OrderResponse)
def add_item_to_cart(
    req: AddItemRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Tap-to-add fallback for customers who'd rather click than talk.

    Mirrors the agent's add_to_order tool: menu item must exist and be
    available. Quantity is accumulated if the item is already in the cart.
    """
    service = OrderService(db)
    cart = service.get_or_create_cart(current_user.id)
    try:
        service.add_item(
            cart.id,
            req.item_id,
            req.quantity,
            req.special_instructions or "",
        )
        db.refresh(cart)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _serialize(cart)


class RemoveItemRequest(BaseModel):
    item_id: str


@router.delete("/current/items/{item_id}", response_model=OrderResponse)
def remove_item_from_cart(
    item_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Remove a menu item from the customer's current cart."""
    service = OrderService(db)
    cart = service.get_or_create_cart(current_user.id)
    try:
        service.remove_item(cart.id, item_id)
        db.refresh(cart)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _serialize(cart)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        return _serialize(OrderService(db).get_order(order_id, current_user.id))
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
