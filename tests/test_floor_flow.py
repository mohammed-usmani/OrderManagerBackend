"""Floor → Zone → Table hierarchy + floor-plan positions + floor snapshot."""

import uuid

from db.models.menu import MenuItem
from services.floor_service import FloorService
from services.order_service import OrderService
from services.table_service import TableService
from services.zone_service import ZoneService


def _menu_item(db, price=400.0):
    mi = MenuItem(
        id=f"F-{uuid.uuid4().hex[:6]}", name="Test Dish", category="mains",
        price=price, currency="INR", available=True,
    )
    db.add(mi)
    db.flush()
    return mi


def _floor_zone_table(db, is_ac=True):
    floor = FloorService(db).create_floor(name=f"Floor-{uuid.uuid4().hex[:5]}", display_order=0)
    zone = ZoneService(db).create_zone(
        name=f"Z-{uuid.uuid4().hex[:5]}", is_ac=is_ac, floor_id=floor.id
    )
    table = TableService(db).create_table(zone_id=zone.id, label=uuid.uuid4().hex[:4], seats=4)
    return floor, zone, table


def test_floor_zone_table_hierarchy(db):
    floor, zone, table = _floor_zone_table(db)
    assert zone.floor_id == floor.id
    # floor_map nests floor → zone → table
    fmap = TableService(db).floor_map()
    f = next((x for x in fmap if x["id"] == floor.id), None)
    assert f is not None
    z = next((x for x in f["zones"] if x["id"] == zone.id), None)
    assert z is not None
    assert any(t["id"] == table.id for t in z["tables"])


def test_delete_floor_blocked_while_zones_attached(db):
    floor, zone, _ = _floor_zone_table(db)
    try:
        FloorService(db).delete_floor(floor.id)
        assert False, "should have refused to delete a non-empty floor"
    except ValueError as e:
        assert "zone" in str(e).lower()


def test_save_positions(db):
    _, _, table = _floor_zone_table(db)
    n = TableService(db).save_positions(
        [{"table_id": table.id, "pos_x": 250, "pos_y": 130, "shape": "rect"}]
    )
    assert n == 1
    db.refresh(table)
    assert (table.pos_x, table.pos_y, table.shape) == (250, 130, "rect")


def test_resolve_qr_includes_floor(db):
    floor, zone, table = _floor_zone_table(db, is_ac=True)
    info = TableService(db).resolve_qr(table.qr_token)
    assert info["floor_id"] == floor.id
    assert info["floor_name"] == floor.name
    assert info["zone_name"] == zone.name
    assert info["is_ac"] is True


def test_dine_in_order_snapshots_floor(db):
    mi = _menu_item(db, 500.0)
    floor, zone, table = _floor_zone_table(db, is_ac=True)
    svc = OrderService(db)
    cart = svc.get_or_create_cart_for_table(
        table.id, zone_name=zone.name, is_ac=True, floor_name=floor.name
    )
    svc.add_item(cart.id, mi.id, 1)
    order = svc.confirm_order(cart.id)
    assert order.floor_name == floor.name
    assert order.zone_name == zone.name
