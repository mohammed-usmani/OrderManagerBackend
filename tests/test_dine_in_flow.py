"""End-to-end dine-in flow: zone/table → table cart → AC bill → rounds →
request bill → settle → receipt. Uses the DB fixture."""

import uuid

from db.models.menu import MenuItem
from services.order_service import OrderService
from services.table_service import TableService
from services.zone_service import ZoneService


def _menu_item(db, price=400.0):
    mi = MenuItem(
        id=f"T-{uuid.uuid4().hex[:6]}",
        name="Test Dish",
        category="mains",
        price=price,
        currency="INR",
        available=True,
    )
    db.add(mi)
    db.flush()
    return mi


def _zone_table(db, is_ac=True):
    zone = ZoneService(db).create_zone(name=f"Z-{uuid.uuid4().hex[:5]}", is_ac=is_ac)
    table = TableService(db).create_table(zone_id=zone.id, label=uuid.uuid4().hex[:4], seats=4)
    return zone, table


def test_dine_in_cart_binds_table_and_bills_ac(db):
    mi = _menu_item(db, 500.0)
    zone, table = _zone_table(db, is_ac=True)
    svc = OrderService(db)

    cart = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=True)
    assert cart.order_type == "dine_in"
    assert cart.table_id == table.id
    assert cart.table_session_id

    svc.add_item(cart.id, mi.id, 2)
    order = svc.confirm_order(cart.id)  # dine-in: no customer
    # 1000 subtotal + 100 service + 50 AC + 50 GST = 1200
    assert order.status == "confirmed"
    assert float(order.total) == 1200.0

    db.refresh(table)
    assert table.status == "occupied"


def test_dine_in_rounds_share_one_session(db):
    mi = _menu_item(db)
    zone, table = _zone_table(db, is_ac=False)
    svc = OrderService(db)

    c1 = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=False)
    sid = c1.table_session_id
    svc.add_item(c1.id, mi.id, 1)
    svc.confirm_order(c1.id)

    c2 = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=False)
    assert c2.id != c1.id
    assert c2.table_session_id == sid  # same running tab


def test_request_bill_then_settle_frees_table(db):
    mi = _menu_item(db, 300.0)
    zone, table = _zone_table(db, is_ac=False)
    svc = OrderService(db)

    cart = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=False)
    sid = cart.table_session_id
    svc.add_item(cart.id, mi.id, 2)
    svc.confirm_order(cart.id)

    svc.request_bill(sid)
    db.refresh(table)
    assert table.status == "needs_bill"

    settled = svc.settle_table_session(sid)
    assert len(settled) == 1
    assert settled[0].status == "paid"
    db.refresh(table)
    assert table.status == "free"

    receipt = TableService(db).session_detail(sid)
    assert receipt["status"] == "closed"
    assert receipt["grand_total"] > 0
    assert len(receipt["orders"]) == 1


def test_resolve_qr_returns_table_context(db):
    zone, table = _zone_table(db, is_ac=True)
    info = TableService(db).resolve_qr(table.qr_token)
    assert info["table_id"] == table.id
    assert info["zone_name"] == zone.name
    assert info["is_ac"] is True


def test_settle_cancels_unfired_cart(db):
    mi = _menu_item(db)
    zone, table = _zone_table(db, is_ac=False)
    svc = OrderService(db)
    cart = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=False)
    sid = cart.table_session_id
    svc.add_item(cart.id, mi.id, 1)  # left in cart, never confirmed
    svc.settle_table_session(sid)
    db.refresh(cart)
    assert cart.status == "cancelled"  # un-fired round dropped, not charged
