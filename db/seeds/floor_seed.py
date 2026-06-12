"""Seed a sample floor layout for Saffron & Smoke.

Two zones to demonstrate the AC-surcharge model: an indoor air-conditioned hall
and an open-air garden (no AC charge). Tables get auto-generated QR tokens (the
model default) the first time they're created, so re-running is idempotent and
existing QR tent cards keep working. Admins can rearrange/extend everything from
the floor-map editor afterwards.
"""

from loguru import logger

from db.models.dining_zone import DiningZone
from db.models.restaurant_table import RestaurantTable
from db.repositories.table_repo import TableRepo
from db.repositories.zone_repo import ZoneRepo

# (zone name, is_ac, display_order, [table labels with their seat counts])
FLOOR: list[tuple[str, bool, int, list[tuple[str, int]]]] = [
    (
        "AC Hall",
        True,
        1,
        [("1", 2), ("2", 2), ("3", 4), ("4", 4), ("5", 6), ("6", 6)],
    ),
    (
        "Garden",
        False,
        2,
        [("G1", 2), ("G2", 4), ("G3", 4), ("G4", 6)],
    ),
]


def seed_floor(db) -> None:
    """Insert any missing zones and tables (idempotent by name / label)."""
    zone_repo = ZoneRepo(db)
    table_repo = TableRepo(db)
    added_zones = added_tables = 0

    for name, is_ac, display_order, tables in FLOOR:
        zone = zone_repo.get_by_name(name)
        if not zone:
            zone = DiningZone(
                name=name, is_ac=is_ac, display_order=display_order, active=True
            )
            db.add(zone)
            db.flush()  # need zone.id for the tables below
            added_zones += 1

        existing = {t.label for t in table_repo.list_all(zone_id=zone.id)}
        for label, seats in tables:
            if label in existing:
                continue
            db.add(RestaurantTable(zone_id=zone.id, label=label, seats=seats))
            added_tables += 1

    if added_zones or added_tables:
        db.flush()
        logger.info(f"Seeded {added_zones} zone(s), {added_tables} table(s)")
