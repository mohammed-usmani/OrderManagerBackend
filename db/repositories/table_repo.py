"""RestaurantTable repository."""

from sqlalchemy.orm import Session

from db.models.restaurant_table import RestaurantTable


class TableRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, table_id: str) -> RestaurantTable | None:
        return self.db.get(RestaurantTable, table_id)

    def get_by_qr_token(self, qr_token: str) -> RestaurantTable | None:
        return (
            self.db.query(RestaurantTable)
            .filter(RestaurantTable.qr_token == qr_token)
            .first()
        )

    def get_by_label(self, label: str) -> RestaurantTable | None:
        """Voice fallback: match a spoken/typed table label (case-insensitive)."""
        return (
            self.db.query(RestaurantTable)
            .filter(RestaurantTable.label.ilike(label.strip()))
            .first()
        )

    def list_all(
        self, zone_id: str | None = None, active_only: bool = False
    ) -> list[RestaurantTable]:
        q = self.db.query(RestaurantTable)
        if zone_id:
            q = q.filter(RestaurantTable.zone_id == zone_id)
        if active_only:
            q = q.filter(RestaurantTable.active == True)  # noqa: E712
        return q.order_by(RestaurantTable.label).all()

    def create(self, **kwargs) -> RestaurantTable:
        table = RestaurantTable(**kwargs)
        self.db.add(table)
        self.db.flush()
        return table

    def update(self, table_id: str, **kwargs) -> RestaurantTable | None:
        table = self.get_by_id(table_id)
        if not table:
            return None
        for key, value in kwargs.items():
            setattr(table, key, value)
        self.db.flush()
        return table

    def delete(self, table_id: str) -> bool:
        table = self.get_by_id(table_id)
        if not table:
            return False
        self.db.delete(table)
        self.db.flush()
        return True
