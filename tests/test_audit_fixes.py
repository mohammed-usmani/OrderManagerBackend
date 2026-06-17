"""Regression tests for the audit fixes (money snapshot, lifecycle, validation)."""

import uuid

import pytest

from db.models.customer import Customer
from db.models.menu import MenuItem
from db.models.table_session import TableSession
from services import billing
from services.billing import bill_for_order
from services.floor_service import FloorService
from services.order_service import OrderService
from services.table_service import TableService
from services.zone_service import ZoneService


def _menu_item(db, price=1000.0):
    mi = MenuItem(id=f"A-{uuid.uuid4().hex[:6]}", name="Dish", category="mains",
                  price=price, currency="INR", available=True)
    db.add(mi); db.flush()
    return mi


def _customer(db):
    c = Customer(code=uuid.uuid4().hex[:4], name="T", area="Bandra West", pincode="400050")
    db.add(c); db.flush()
    return c


def _floor_zone_table(db, **zkw):
    floor = FloorService(db).create_floor(name=f"F-{uuid.uuid4().hex[:5]}")
    zone = ZoneService(db).create_zone(name=f"Z-{uuid.uuid4().hex[:5]}", floor_id=floor.id, **zkw)
    table = TableService(db).create_table(zone_id=zone.id, label="X", seats=2)
    return floor, zone, table


def test_confirmed_order_total_uses_frozen_snapshot(db):
    """A confirmed order's bill must not change when the charge policy changes."""
    mi = _menu_item(db, 1000.0)
    cust = _customer(db)
    svc = OrderService(db)
    cart = svc.get_or_create_cart_for_customer(cust.id)
    svc.add_item(cart.id, mi.id, 1)
    order = svc.confirm_order(cart.id, customer=cust)
    before = bill_for_order(order)["total"]

    billing.set_policy_override([{"key": "x", "label": "X", "rate": 0.5, "applies_to": "all"}])
    try:
        after = bill_for_order(order)["total"]
    finally:
        billing.set_policy_override(None)
    assert after == before  # snapshot, not recomputed with the new policy


def test_cannot_change_items_on_confirmed_order(db):
    mi = _menu_item(db)
    cust = _customer(db)
    svc = OrderService(db)
    cart = svc.get_or_create_cart_for_customer(cust.id)
    svc.add_item(cart.id, mi.id, 1)
    svc.confirm_order(cart.id, customer=cust)
    with pytest.raises(ValueError):
        svc.add_item(cart.id, mi.id, 1)  # cart is now 'confirmed'


def test_dine_in_cancel_frees_table(db):
    mi = _menu_item(db)
    _, zone, table = _floor_zone_table(db, is_ac=True)
    svc = OrderService(db)
    cart = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=True)
    sid = cart.table_session_id
    svc.add_item(cart.id, mi.id, 1)
    svc.confirm_order(cart.id)
    db.refresh(table)
    assert table.status == "occupied"

    svc.advance_status(cart.id, "cancelled")  # confirmed -> cancelled
    db.refresh(table)
    assert table.status == "free"
    assert db.get(TableSession, sid).status == "closed"


def test_create_zone_rejects_unknown_floor(db):
    with pytest.raises(ValueError, match="Floor not found"):
        ZoneService(db).create_zone(name="Z", floor_id="does-not-exist")


def test_resolve_qr_rejects_inactive_zone(db):
    _, _, table = _floor_zone_table(db, active=False)
    with pytest.raises(ValueError):
        TableService(db).resolve_qr(table.qr_token)
