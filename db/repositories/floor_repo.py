"""Floor repository."""

from sqlalchemy.orm import Session

from db.models.floor import Floor


class FloorRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, floor_id: str) -> Floor | None:
        return self.db.get(Floor, floor_id)

    def get_by_name(self, name: str) -> Floor | None:
        return self.db.query(Floor).filter(Floor.name == name).first()

    def list_all(self, active_only: bool = False) -> list[Floor]:
        q = self.db.query(Floor)
        if active_only:
            q = q.filter(Floor.active == True)  # noqa: E712
        return q.order_by(Floor.display_order, Floor.name).all()

    def create(self, **kwargs) -> Floor:
        floor = Floor(**kwargs)
        self.db.add(floor)
        self.db.flush()
        return floor

    def update(self, floor_id: str, **kwargs) -> Floor | None:
        floor = self.get_by_id(floor_id)
        if not floor:
            return None
        for key, value in kwargs.items():
            setattr(floor, key, value)
        self.db.flush()
        return floor

    def delete(self, floor_id: str) -> bool:
        floor = self.get_by_id(floor_id)
        if not floor:
            return False
        self.db.delete(floor)
        self.db.flush()
        return True
