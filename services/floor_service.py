"""Floor service — storeys at the top of the Floor → Zone → Table hierarchy."""

from sqlalchemy.orm import Session

from db.repositories.floor_repo import FloorRepo
from db.repositories.zone_repo import ZoneRepo


class FloorService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = FloorRepo(db)
        self.zone_repo = ZoneRepo(db)

    def list_floors(self, active_only: bool = False):
        return self.repo.list_all(active_only=active_only)

    def create_floor(self, **kwargs):
        return self.repo.create(**kwargs)

    def update_floor(self, floor_id: str, **kwargs):
        floor = self.repo.update(floor_id, **kwargs)
        if not floor:
            raise ValueError("Floor not found")
        return floor

    def delete_floor(self, floor_id: str) -> None:
        if not self.repo.get_by_id(floor_id):
            raise ValueError("Floor not found")
        # Don't orphan zones — require the floor be emptied first.
        if self.zone_repo.list_all(floor_id=floor_id):
            raise ValueError("Floor still has zones; move or delete them first")
        self.repo.delete(floor_id)
