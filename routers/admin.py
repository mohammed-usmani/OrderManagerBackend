"""Admin router: order fulfilment, analytics.

All endpoints require an admin JWT. Customers can't reach these.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from db.models.menu import MenuItem
from db.models.order import Order, OrderItem
from db.models.user import User
from dependencies import require_admin
from pipeline.ui_events import compute_bill
from routers.menu import MenuItemResponse
from services.menu_service import MenuService
from services.order_service import OrderService

RESTAURANT_TZ = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/admin", tags=["admin"])


# --- Response models ---

class AdminOrderItem(BaseModel):
    id: str
    menu_item_id: str
    name: str
    quantity: int
    price_at_order: float
    line_total: float
    special_instructions: str | None

    model_config = {"from_attributes": True}


class AdminBillCharge(BaseModel):
    label: str
    rate: float
    amount: float


class AdminOrderResponse(BaseModel):
    id: str
    status: str
    created_at: datetime
    confirmed_at: datetime | None
    paid_at: datetime | None
    customer_email: str
    customer_name: str
    item_count: int
    subtotal: float
    charges: list[AdminBillCharge]
    total: float
    items: list[AdminOrderItem]


class UpdateStatusRequest(BaseModel):
    status: str  # one of: awaiting_payment | paid | cancelled


# --- Helpers ---

_VALID_TRANSITIONS = {"awaiting_payment", "paid", "cancelled"}


def _serialize_order(order, db) -> AdminOrderResponse:
    menu_service = MenuService(db)
    customer = db.get(User, order.user_id)
    items: list[AdminOrderItem] = []
    for oi in order.items:
        try:
            name = menu_service.get_item(oi.menu_item_id, include_unavailable=True).name
        except ValueError:
            name = oi.menu_item_id
        price = float(oi.price_at_order)
        items.append(
            AdminOrderItem(
                id=oi.id,
                menu_item_id=oi.menu_item_id,
                name=name,
                quantity=oi.quantity,
                price_at_order=price,
                line_total=price * oi.quantity,
                special_instructions=oi.special_instructions,
            )
        )
    subtotal = sum(i.line_total for i in items)
    bill = compute_bill(subtotal)
    return AdminOrderResponse(
        id=order.id,
        status=order.status,
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        paid_at=order.paid_at,
        customer_email=customer.email if customer else "",
        customer_name=customer.name if customer else "",
        item_count=sum(i.quantity for i in items),
        subtotal=bill["subtotal"],
        charges=[AdminBillCharge(**c) for c in bill["charges"]],
        total=bill["total"],
        items=items,
    )


# --- Endpoints ---

@router.get("/orders", response_model=list[AdminOrderResponse])
def list_orders(
    status: str | None = Query(
        default=None,
        description="Filter: 'active' (confirmed+awaiting_payment), 'all', or a specific status",
    ),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """List orders for the kitchen dashboard.

    `status=active` is the default kitchen view — confirmed + awaiting_payment.
    `status=all` returns every order. Anything else is treated as an exact status.
    """
    if status is None or status == "active":
        target = ["confirmed", "awaiting_payment"]
    elif status == "all":
        target = None
    else:
        target = [status]

    orders = OrderService(db).list_orders_admin(statuses=target)
    return [_serialize_order(o, db) for o in orders]


@router.patch("/orders/{order_id}/status", response_model=AdminOrderResponse)
def update_order_status(
    order_id: str,
    req: UpdateStatusRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Transition an order's status. Valid targets: awaiting_payment | paid | cancelled."""
    new_status = req.status.strip().lower()
    if new_status not in _VALID_TRANSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target status '{new_status}'. Valid: {sorted(_VALID_TRANSITIONS)}",
        )

    service = OrderService(db)
    try:
        if new_status == "awaiting_payment":
            service.mark_awaiting_payment(order_id)
        elif new_status == "paid":
            # Allow paid from confirmed too — step through awaiting_payment.
            order = service.get_order_admin(order_id)
            if order.status == "confirmed":
                service.mark_awaiting_payment(order_id)
            service.mark_paid(order_id)
        elif new_status == "cancelled":
            service.cancel_order(order_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    order = service.get_order_admin(order_id)
    return _serialize_order(order, db)


# --- Analytics ---

class TopItem(BaseModel):
    menu_item_id: str
    name: str
    quantity: int
    revenue: float  # subtotal contribution (price_at_order × quantity)


class AnalyticsSummary(BaseModel):
    range: str
    range_start: datetime
    orders_by_status: dict[str, int]
    total_orders: int
    revenue_subtotal: float       # sum of item line totals for non-cancelled orders
    revenue_with_charges: float   # after service charge + GST
    top_items: list[TopItem]


_RANGE_DAYS = {"today": 0, "7d": 7, "30d": 30, "all": None}


def _range_start(range_key: str) -> datetime | None:
    """Return the UTC datetime from which orders count towards the range.

    "today" = midnight in the restaurant's timezone (IST).
    Others  = N days before now (rolling window).
    "all"   = None (no filter).
    """
    if range_key == "today":
        now_ist = datetime.now(RESTAURANT_TZ)
        midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.astimezone(timezone.utc).replace(tzinfo=None)
    days = _RANGE_DAYS.get(range_key)
    if days is None:
        return None
    return datetime.utcnow() - timedelta(days=days)


@router.get("/analytics/summary", response_model=AnalyticsSummary)
def analytics_summary(
    range: str = Query("today", description="today | 7d | 30d | all"),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Compact metrics for the admin dashboard."""
    if range not in _RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid range '{range}'. Valid: {sorted(_RANGE_DAYS)}",
        )

    q = db.query(Order)
    start = _range_start(range)
    if start is not None:
        q = q.filter(Order.created_at >= start)
    orders = q.all()

    status_counts: dict[str, int] = defaultdict(int)
    for o in orders:
        status_counts[o.status] += 1

    # Revenue counts everything except cancelled + still-in-cart.
    revenue_subtotal = 0.0
    item_stats: dict[str, dict] = {}
    for o in orders:
        if o.status in ("cancelled", "cart"):
            continue
        for oi in o.items:
            line = float(oi.price_at_order) * oi.quantity
            revenue_subtotal += line
            stat = item_stats.setdefault(
                oi.menu_item_id,
                {"menu_item_id": oi.menu_item_id, "quantity": 0, "revenue": 0.0},
            )
            stat["quantity"] += oi.quantity
            stat["revenue"] += line

    # Fill in names from MenuService.
    menu_service = MenuService(db)
    top_items: list[TopItem] = []
    for stat in sorted(item_stats.values(), key=lambda s: -s["quantity"])[:5]:
        try:
            name = menu_service.get_item(stat["menu_item_id"], include_unavailable=True).name
        except ValueError:
            name = stat["menu_item_id"]
        top_items.append(
            TopItem(
                menu_item_id=stat["menu_item_id"],
                name=name,
                quantity=stat["quantity"],
                revenue=stat["revenue"],
            )
        )

    revenue_with_charges = compute_bill(revenue_subtotal)["total"]

    return AnalyticsSummary(
        range=range,
        range_start=start or datetime(1970, 1, 1),
        orders_by_status=dict(status_counts),
        total_orders=len(orders),
        revenue_subtotal=revenue_subtotal,
        revenue_with_charges=revenue_with_charges,
        top_items=top_items,
    )


# --- Menu admin list (includes disabled items) ---

@router.get("/menu", response_model=list[MenuItemResponse])
def admin_list_menu(
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """All menu items, including disabled — for the admin menu editor."""
    return MenuService(db).list_items(include_unavailable=True)
