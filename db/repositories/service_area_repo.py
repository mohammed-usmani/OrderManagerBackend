"""ServiceArea repository."""

from sqlalchemy.orm import Session

from db.models.service_area import ServiceArea


class ServiceAreaRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, area_id: str) -> ServiceArea | None:
        return self.db.get(ServiceArea, area_id)

    def list_all(self, active_only: bool = False) -> list[ServiceArea]:
        q = self.db.query(ServiceArea)
        if active_only:
            q = q.filter(ServiceArea.active == True)  # noqa: E712
        return q.order_by(ServiceArea.name).all()

    def create(self, **kwargs) -> ServiceArea:
        area = ServiceArea(**kwargs)
        self.db.add(area)
        self.db.flush()
        return area

    def update(self, area_id: str, **kwargs) -> ServiceArea | None:
        area = self.get_by_id(area_id)
        if not area:
            return None
        for key, value in kwargs.items():
            setattr(area, key, value)
        self.db.flush()
        return area

    def delete(self, area_id: str) -> bool:
        area = self.get_by_id(area_id)
        if not area:
            return False
        self.db.delete(area)
        self.db.flush()
        return True
