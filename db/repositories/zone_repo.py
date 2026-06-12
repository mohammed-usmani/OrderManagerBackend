"""DiningZone repository."""

from sqlalchemy.orm import Session

from db.models.dining_zone import DiningZone


class ZoneRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, zone_id: str) -> DiningZone | None:
        return self.db.get(DiningZone, zone_id)

    def get_by_name(self, name: str) -> DiningZone | None:
        return (
            self.db.query(DiningZone)
            .filter(DiningZone.name == name)
            .first()
        )

    def list_all(self, active_only: bool = False) -> list[DiningZone]:
        q = self.db.query(DiningZone)
        if active_only:
            q = q.filter(DiningZone.active == True)  # noqa: E712
        return q.order_by(DiningZone.display_order, DiningZone.name).all()

    def create(self, **kwargs) -> DiningZone:
        zone = DiningZone(**kwargs)
        self.db.add(zone)
        self.db.flush()
        return zone

    def update(self, zone_id: str, **kwargs) -> DiningZone | None:
        zone = self.get_by_id(zone_id)
        if not zone:
            return None
        for key, value in kwargs.items():
            setattr(zone, key, value)
        self.db.flush()
        return zone

    def delete(self, zone_id: str) -> bool:
        zone = self.get_by_id(zone_id)
        if not zone:
            return False
        self.db.delete(zone)
        self.db.flush()
        return True
