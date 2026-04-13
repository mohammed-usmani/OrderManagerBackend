"""Menu service: CRUD for menu items."""

from sqlalchemy.orm import Session

from db.models.menu import MenuItem
from db.repositories.menu_repo import MenuRepo


class MenuService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MenuRepo(db)

    def list_items(self, include_unavailable: bool = False) -> list[MenuItem]:
        return self.repo.list_all(include_unavailable=include_unavailable)

    def get_item(self, item_id: str, include_unavailable: bool = False) -> MenuItem:
        item = self.repo.get_by_id(item_id)
        if not item:
            raise ValueError(f"Menu item '{item_id}' not found")
        if not include_unavailable and not item.available:
            raise ValueError(f"Menu item '{item_id}' not found")
        return item

    def find_by_name(self, query: str) -> list[MenuItem]:
        return self.repo.find_by_name(query)

    def create_item(self, **kwargs) -> MenuItem:
        return self.repo.create(**kwargs)

    def update_item(self, item_id: str, **kwargs) -> MenuItem:
        item = self.repo.update(item_id, **kwargs)
        if not item:
            raise ValueError(f"Menu item '{item_id}' not found")
        return item

    def disable_item(self, item_id: str) -> None:
        if not self.repo.update(item_id, available=False):
            raise ValueError(f"Menu item '{item_id}' not found")

    def item_count(self) -> int:
        return self.repo.count()
