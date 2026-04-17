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

    def search(self, query: str) -> list[MenuItem]:
        """Smart keyword search: tokens match across name, description,
        taste profile, preparation notes, category, spice level, and dietary
        tags. Ranked by hit count."""
        return self.repo.search_keywords(query)

    def filter(
        self,
        *,
        category: str | None = None,
        dietary: list[str] | None = None,
        spice_level: str | None = None,
        max_price: float | None = None,
        keyword: str | None = None,
    ) -> list[MenuItem]:
        """AND-filter items by any combination of category, dietary tags,
        spice level, max price, or keyword."""
        return self.repo.filter_items(
            category=category,
            dietary=dietary,
            spice_level=spice_level,
            max_price=max_price,
            keyword=keyword,
        )

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
