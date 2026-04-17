"""MenuItem repository."""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.models.menu import MenuItem


class MenuRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, item_id: str) -> MenuItem | None:
        return self.db.get(MenuItem, item_id)

    def list_all(self, include_unavailable: bool = False) -> list[MenuItem]:
        q = self.db.query(MenuItem)
        if not include_unavailable:
            q = q.filter(MenuItem.available == True)  # noqa: E712
        return q.order_by(MenuItem.category, MenuItem.id).all()

    def find_by_name(self, query: str) -> list[MenuItem]:
        """Match any whitespace-separated token against the name.

        "chicken tikka" matches both "Butter Chicken" and
        "Tandoori Paneer Tikka" instead of requiring the full phrase.
        """
        tokens = [t for t in query.strip().split() if t]
        if not tokens:
            return []
        conditions = [MenuItem.name.ilike(f"%{t}%") for t in tokens]
        return self.db.query(MenuItem).filter(or_(*conditions)).all()

    def create(self, **kwargs) -> MenuItem:
        item = MenuItem(**kwargs)
        self.db.add(item)
        self.db.flush()
        return item

    def update(self, item_id: str, **kwargs) -> MenuItem | None:
        item = self.get_by_id(item_id)
        if not item:
            return None
        for key, value in kwargs.items():
            setattr(item, key, value)
        self.db.flush()
        return item

    def count(self) -> int:
        return self.db.query(MenuItem).count()
