"""Dining-zone service: rooms/sections of the floor (and the AC flag)."""

from sqlalchemy.orm import Session

from db.repositories.floor_repo import FloorRepo
from db.repositories.table_repo import TableRepo
from db.repositories.zone_repo import ZoneRepo


class ZoneService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ZoneRepo(db)
        self.table_repo = TableRepo(db)

    def list_zones(self, active_only: bool = False):
        return self.repo.list_all(active_only=active_only)

    def get_zone(self, zone_id: str):
        zone = self.repo.get_by_id(zone_id)
        if not zone:
            raise ValueError("Zone not found")
        return zone

    def create_zone(self, **kwargs):
        floor_id = kwargs.get("floor_id")
        if floor_id is not None and not FloorRepo(self.db).get_by_id(floor_id):
            raise ValueError("Floor not found")
        return self.repo.create(**kwargs)

    def update_zone(self, zone_id: str, **kwargs):
        zone = self.repo.update(zone_id, **kwargs)
        if not zone:
            raise ValueError("Zone not found")
        return zone

    def save_positions(self, updates: list[dict]) -> int:
        """Bulk-apply zone rectangles: [{zone_id, pos_x, pos_y, width, height}].

        Skips unknown zones; only sets provided (non-None) fields. Returns count.
        """
        n = 0
        for u in updates:
            zone = self.repo.get_by_id(u.get("zone_id"))
            if not zone:
                continue
            for key in ("pos_x", "pos_y", "width", "height"):
                if u.get(key) is not None:
                    setattr(zone, key, u[key])
            n += 1
        self.db.flush()
        return n

    def delete_zone(self, zone_id: str) -> None:
        if not self.repo.get_by_id(zone_id):
            raise ValueError("Zone not found")
        # Don't orphan tables — require the zone be emptied first.
        if self.table_repo.list_all(zone_id=zone_id):
            raise ValueError("Zone still has tables; move or delete them first")
        self.repo.delete(zone_id)
