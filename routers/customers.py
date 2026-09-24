"""Customers router: admin-only management of parcel customer records."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from db.repositories.order_repo import OrderRepo
from dependencies import require_admin
from pipeline.ui_events import compute_bill
from services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerResponse(BaseModel):
    id: str
    code: str
    phone: str | None
    name: str | None
    address_line: str | None
    area: str | None
    pincode: str | None
    landmark: str | None
    preferences: str | None
    allergies: str | None
    notes: str | None
    order_count: int
    last_order_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateCustomerRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    address_line: str | None = None
    area: str | None = None
    pincode: str | None = None
    landmark: str | None = None
    preferences: str | None = None
    allergies: str | None = None
    notes: str | None = None


class UpdateCustomerRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    address_line: str | None = None
    area: str | None = None
    pincode: str | None = None
    landmark: str | None = None
    preferences: str | None = None
    allergies: str | None = None
    notes: str | None = None


class CustomerOrderSummary(BaseModel):
    id: str
    status: str
    created_at: datetime
    item_count: int
    subtotal: float
    total: float


class CustomerPage(BaseModel):
    items: list[CustomerResponse]
    total: int
    limit: int
    offset: int


@router.get("", response_model=CustomerPage)
def list_customers(
    search: str | None = Query(default=None, description="Match code, phone, name, or area"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    items, total = CustomerService(db).search_page(query=search, limit=limit, offset=offset)
    return CustomerPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        return CustomerService(db).get_by_id(customer_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{customer_id}/orders", response_model=list[CustomerOrderSummary])
def get_customer_orders(
    customer_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    orders = OrderRepo(db).get_all_for_customer(customer_id)
    summaries: list[CustomerOrderSummary] = []
    for o in orders:
        subtotal = 0.0
        count = 0
        for oi in o.items:
            subtotal += float(oi.price_at_order) * oi.quantity
            count += oi.quantity
        bill = compute_bill(subtotal)
        summaries.append(
            CustomerOrderSummary(
                id=o.id,
                status=o.status,
                created_at=o.created_at,
                item_count=count,
                subtotal=bill["subtotal"],
                total=bill["total"],
            )
        )
    return summaries


@router.post("", response_model=CustomerResponse, status_code=201)
def create_customer(
    req: CreateCustomerRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    customer = CustomerService(db).create_customer(**req.model_dump())
    db.commit()
    return customer


@router.patch("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: str,
    req: UpdateCustomerRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        customer = CustomerService(db).update_customer(
            customer_id, **req.model_dump(exclude_unset=True)
        )
        db.commit()
        return customer
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
