"""Seed a sample multi-floor layout for Saffron & Smoke.

Floor → Zone → Table, with tables pre-placed on the floor-plan canvas so the
admin map isn't empty on first load. Ground Floor demonstrates the AC-surcharge
model (an AC hall + an open-air garden); a Rooftop floor shows multi-storey.
Idempotent: floors by name, zones by name, tables by label. It also *attaches*
any pre-existing zones to their floor and back-fills positions onto tables that
don't have one yet (e.g. rows created before the floor-plan feature).
"""

from loguru import logger

from db.models.dining_zone import DiningZone
from db.models.restaurant_table import RestaurantTable
from db.repositories.floor_repo import FloorRepo
from db.repositories.table_repo import TableRepo
from db.repositories.zone_repo import ZoneRepo

# floor name, display_order, [ (zone name, is_ac, zone display_order,
#                               [(table label, seats)]) ]
FLOORS: list[tuple[str, int, list[tuple[str, bool, int, list[tuple[str, int]]]]]] = [
    (
        "Ground Floor",
        0,
        [
            ("AC Hall", True, 1, [("1", 2), ("2", 2), ("3", 4), ("4", 4), ("5", 6), ("6", 6)]),
            ("Garden", False, 2, [("G1", 2), ("G2", 4), ("G3", 4), ("G4", 6)]),
        ],
    ),
    (
        "Rooftop",
        1,
        [
            ("Rooftop Lounge", False, 1, [("R1", 2), ("R2", 2), ("R3", 4), ("R4", 6)]),
        ],
    ),
]

# Grid placement within the 1000×640 logical canvas.
_COLS, _CELL_W, _CELL_H, _X0, _Y0 = 6, 150, 140, 90, 90


def _shape_for(seats: int) -> str:
    if seats <= 2:
        return "round"
    if seats <= 4:
        return "square"
    return "rect"


def seed_floor(db) -> None:
    """Insert/attach floors, zones and tables; back-fill table positions."""
    floor_repo = FloorRepo(db)
    zone_repo = ZoneRepo(db)
    table_repo = TableRepo(db)
    added_floors = added_zones = added_tables = placed = 0

    for floor_name, floor_order, zones in FLOORS:
        floor = floor_repo.get_by_name(floor_name)
        if not floor:
            floor = floor_repo.create(name=floor_name, display_order=floor_order)
            added_floors += 1

        slot = 0  # running grid index across the whole floor
        for zone_name, is_ac, zone_order, tables in zones:
            zone = zone_repo.get_by_name(zone_name)
            if not zone:
                zone = DiningZone(
                    name=zone_name, is_ac=is_ac, display_order=zone_order,
                    active=True, floor_id=floor.id,
                )
                db.add(zone)
                db.flush()
                added_zones += 1
            elif zone.floor_id != floor.id:
                zone.floor_id = floor.id  # attach legacy zone to its floor
                db.flush()

            existing = {t.label: t for t in table_repo.list_all(zone_id=zone.id)}
            for label, seats in tables:
                col, row = slot % _COLS, slot // _COLS
                pos_x, pos_y = _X0 + col * _CELL_W, _Y0 + row * _CELL_H
                slot += 1
                t = existing.get(label)
                if t is None:
                    db.add(RestaurantTable(
                        zone_id=zone.id, label=label, seats=seats,
                        shape=_shape_for(seats), pos_x=pos_x, pos_y=pos_y,
                    ))
                    added_tables += 1
                elif t.pos_x is None or t.pos_y is None:
                    t.pos_x, t.pos_y = pos_x, pos_y  # back-fill a position
                    if not t.shape:
                        t.shape = _shape_for(t.seats)
                    placed += 1

    if added_floors or added_zones or added_tables or placed:
        db.flush()
        logger.info(
            f"Seeded {added_floors} floor(s), {added_zones} zone(s), "
            f"{added_tables} table(s); placed {placed} existing table(s)"
        )
