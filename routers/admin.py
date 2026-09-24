"""Admin router: order fulfilment, analytics.

All endpoints require an admin JWT. Customers can't reach these.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from db.models.customer import Customer
from db.models.order import Order
from db.models.restaurant_table import RestaurantTable
from db.models.user import User
from dependencies import require_admin, require_roles
from routers.menu import MenuItemResponse
from services import order_lifecycle as lifecycle
from services.billing import bill_for_order
from services.auth_service import auth_service
from services.events import subscribe_order_events
from services.roles import CASHIER_ROLES, STAFF_ROLES

# KDS (view orders + advance status) is open to any on-shift staff member.
_require_staff = require_roles(STAFF_ROLES)
# Edits / voids / refunds are restricted to cashiers and managers.
_require_cashier = require_roles(CASHIER_ROLES)
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
    status: str = "pending"
    void_reason: str | None = None

    model_config = {"from_attributes": True}


class AdminBillCharge(BaseModel):
    label: str
    rate: float
    amount: float


class AdminOrderResponse(BaseModel):
    id: str
    status: str
    order_type: str
    created_at: datetime
    confirmed_at: datetime | None
    served_at: datetime | None
    ready_at: datetime | None
    delivered_at: datetime | None
    paid_at: datetime | None
    customer_email: str
    customer_name: str
    customer_code: str | None
    contact_phone: str | None
    delivery_address: str | None
    delivery_area: str | None
    delivery_pincode: str | None
    # Dine-in context (None for parcel orders).
    table_id: str | None
    table_label: str | None
    table_session_id: str | None
    zone_name: str | None
    floor_name: str | None
    is_ac: bool | None
    # The statuses this order may legally move to next (drives the KDS buttons).
    next_statuses: list[str]
    item_count: int
    subtotal: float
    charges: list[AdminBillCharge]
    total: float
    items: list[AdminOrderItem]
    refunded: bool = False
    cancellation_reason: str | None = None


class UpdateStatusRequest(BaseModel):
    status: str  # any legal lifecycle target (validated by the state machine)


class CancelOrderRequest(BaseModel):
    reason: str | None = None


class EditItemRequest(BaseModel):
    menu_item_id: str
    quantity: int
    special_instructions: str = ""


class VoidItemRequest(BaseModel):
    order_item_id: str
    reason: str


class ItemStatusRequest(BaseModel):
    order_item_id: str
    status: str  # pending | ready | served


class RefundRequest(BaseModel):
    reason: str


# --- Helpers ---

# Kitchen board default view: everything still needing work.
_ACTIVE_STATUSES = sorted(lifecycle.OPEN_STATUSES)


def _serialize_order(order, db) -> AdminOrderResponse:
    menu_service = MenuService(db)
    # Parcel orders are tied to a Customer; legacy orders to a User.
    parcel_customer = db.get(Customer, order.customer_id) if order.customer_id else None
    user = db.get(User, order.user_id) if order.user_id else None
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
                status=oi.status,
                void_reason=oi.void_reason,
            )
        )
    # Context-aware bill, preferring the snapshot frozen at confirm time.
    bill = bill_for_order(order)
    # Prefer the snapshot frozen on the order at confirm time; fall back to the
    # live customer record for in-progress carts.
    contact_name = order.contact_name or (parcel_customer.name if parcel_customer else None)
    contact_phone = order.contact_phone or (parcel_customer.phone if parcel_customer else None)
    delivery_address = order.delivery_address or (parcel_customer.address_line if parcel_customer else None)
    delivery_area = order.delivery_area or (parcel_customer.area if parcel_customer else None)
    delivery_pincode = order.delivery_pincode or (parcel_customer.pincode if parcel_customer else None)
    customer_name = contact_name or (user.name if user else "")

    table = db.get(RestaurantTable, order.table_id) if order.table_id else None

    return AdminOrderResponse(
        id=order.id,
        status=order.status,
        order_type=order.order_type,
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        served_at=order.served_at,
        ready_at=order.ready_at,
        delivered_at=order.delivered_at,
        paid_at=order.paid_at,
        customer_email=user.email if user else "",
        customer_name=customer_name or "",
        customer_code=parcel_customer.code if parcel_customer else None,
        contact_phone=contact_phone,
        delivery_address=delivery_address,
        delivery_area=delivery_area,
        delivery_pincode=delivery_pincode,
        table_id=order.table_id,
        table_label=table.label if table else None,
        table_session_id=order.table_session_id,
        zone_name=order.zone_name,
        floor_name=order.floor_name,
        is_ac=order.is_ac,
        next_statuses=sorted(lifecycle.allowed_next(order.order_type or "parcel", order.status)),
        item_count=sum(i.quantity for i in items),
        subtotal=bill["subtotal"],
        charges=[AdminBillCharge(**c) for c in bill["charges"]],
        total=bill["total"],
        items=items,
        refunded=bool(order.refunded),
        cancellation_reason=order.cancellation_reason,
    )


# --- Endpoints ---

@router.get("/orders/stream")
async def stream_orders(token: str = Query(..., description="JWT (EventSource can't send headers)")):
    """Server-sent stream of order-board change events for the live KDS.

    Auth is via the ``token`` query param because the browser's EventSource API
    cannot set an Authorization header. Any on-shift staff role may subscribe.
    """
    try:
        payload = auth_service.decode_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Staff access required")

    async def gen():
        yield "retry: 3000\n\n"  # client reconnect backoff
        async for data in subscribe_order_events():
            yield f"data: {data}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering
        },
    )


@router.get("/orders", response_model=list[AdminOrderResponse])
def list_orders(
    status: str | None = Query(
        default=None,
        description="Filter: 'active' (confirmed+awaiting_payment), 'all', or a specific status",
    ),
    db: Session = Depends(get_db),
    _=Depends(_require_staff),
):
    """List orders for the kitchen dashboard.

    `status=active` is the default kitchen view — confirmed + awaiting_payment.
    `status=all` returns every order. Anything else is treated as an exact status.
    """
    if status is None or status == "active":
        target = _ACTIVE_STATUSES
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
    _=Depends(_require_staff),
):
    """Advance an order along its lifecycle (validated by the state machine).

    Dine-in: confirmed → cooking → served → paid.
    Parcel:  confirmed → cooking → ready → delivered → paid.
    Either may be cancelled before payment.
    """
    new_status = req.status.strip().lower()
    service = OrderService(db)
    try:
        service.advance_status(order_id, new_status)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    order = service.get_order_admin(order_id)
    return _serialize_order(order, db)


def _order_op(db, fn):
    """Run an order-service mutation, commit, and return the serialized order."""
    try:
        order = fn()
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return _serialize_order(order, db)


@router.post("/orders/{order_id}/cancel", response_model=AdminOrderResponse)
def cancel_order_admin(
    order_id: str, req: CancelOrderRequest,
    db: Session = Depends(get_db), actor=Depends(_require_staff),
):
    return _order_op(db, lambda: OrderService(db).cancel_order(order_id, req.reason, actor))


@router.patch("/orders/{order_id}/items", response_model=AdminOrderResponse)
def edit_order_item(
    order_id: str, req: EditItemRequest,
    db: Session = Depends(get_db), actor=Depends(_require_cashier),
):
    return _order_op(db, lambda: OrderService(db).edit_item_admin(
        order_id, req.menu_item_id, req.quantity, req.special_instructions, actor))


@router.post("/orders/{order_id}/void-item", response_model=AdminOrderResponse)
def void_order_item(
    order_id: str, req: VoidItemRequest,
    db: Session = Depends(get_db), actor=Depends(_require_cashier),
):
    return _order_op(db, lambda: OrderService(db).void_item(
        order_id, req.order_item_id, req.reason, actor))


@router.patch("/orders/{order_id}/item-status", response_model=AdminOrderResponse)
def set_order_item_status(
    order_id: str, req: ItemStatusRequest,
    db: Session = Depends(get_db), _=Depends(_require_staff),
):
    return _order_op(db, lambda: OrderService(db).set_item_status(
        order_id, req.order_item_id, req.status.strip().lower()))


@router.post("/orders/{order_id}/refund", response_model=AdminOrderResponse)
def refund_order_admin(
    order_id: str, req: RefundRequest,
    db: Session = Depends(get_db), actor=Depends(_require_cashier),
):
    return _order_op(db, lambda: OrderService(db).refund_order(order_id, req.reason, actor))


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
    revenue_with_charges = 0.0
    item_stats: dict[str, dict] = {}
    for o in orders:
        if o.status in ("cancelled", "cart"):
            continue
        # Per-order bill (frozen snapshot when present) so charges reflect each
        # order's real context (AC/dine-in) — not parcel defaults on an aggregate.
        revenue_with_charges += bill_for_order(o)["total"]
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
