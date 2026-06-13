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


def test_zone_created_with_geometry(db):
    floor = FloorService(db).create_floor(name=f"Floor-{uuid.uuid4().hex[:5]}")
    zone = ZoneService(db).create_zone(
        name=f"Z-{uuid.uuid4().hex[:5]}", floor_id=floor.id,
        pos_x=120, pos_y=80, width=400, height=300,
    )
    assert (zone.pos_x, zone.pos_y, zone.width, zone.height) == (120, 80, 400, 300)


def test_zone_defaults_geometry_when_omitted(db):
    floor = FloorService(db).create_floor(name=f"Floor-{uuid.uuid4().hex[:5]}")
    zone = ZoneService(db).create_zone(name=f"Z-{uuid.uuid4().hex[:5]}", floor_id=floor.id)
    # NOT NULL columns get the model defaults — never None for the frontend.
    assert zone.pos_x is not None and zone.width is not None


def test_zone_save_positions_bulk(db):
    _, zone, _ = _floor_zone_table(db)
    n = ZoneService(db).save_positions(
        [{"zone_id": zone.id, "pos_x": 300, "pos_y": 150, "width": 500, "height": 360}]
    )
    assert n == 1
    db.refresh(zone)
    assert (zone.pos_x, zone.pos_y, zone.width, zone.height) == (300, 150, 500, 360)


def test_floor_map_includes_zone_geometry(db):
    floor, zone, _ = _floor_zone_table(db)
    fmap = TableService(db).floor_map()
    f = next(x for x in fmap if x["id"] == floor.id)
    z = next(x for x in f["zones"] if x["id"] == zone.id)
    assert {"pos_x", "pos_y", "width", "height"} <= set(z)


def test_table_drop_reassigns_zone(db):
    # Two zones on one floor; moving a table to the other zone (drop-to-assign).
    floor = FloorService(db).create_floor(name=f"Floor-{uuid.uuid4().hex[:5]}")
    z1 = ZoneService(db).create_zone(name=f"A-{uuid.uuid4().hex[:5]}", floor_id=floor.id)
    z2 = ZoneService(db).create_zone(name=f"B-{uuid.uuid4().hex[:5]}", floor_id=floor.id)
    table = TableService(db).create_table(zone_id=z1.id, label="X", seats=2)
    # frontend persists drop-to-assign via the table positions endpoint
    TableService(db).save_positions(
        [{"table_id": table.id, "zone_id": z2.id, "pos_x": 50, "pos_y": 50}]
    )
    db.refresh(table)
    assert table.zone_id == z2.id


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
