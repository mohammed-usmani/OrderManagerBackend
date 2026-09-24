"""Menu service: CRUD for menu items."""

from sqlalchemy.orm import Session

from db.models.menu import MenuItem
from db.repositories.menu_repo import MenuRepo
from services.embeddings import embed_text, embed_texts, embeddings_enabled


def effective_available(item: MenuItem) -> bool:
    """A dish is orderable only if it's enabled, not 86'd, and (if stock-tracked)
    still in stock."""
    if not item.available or item.is_86:
        return False
    if item.track_stock and (item.stock_qty or 0) <= 0:
        return False
    return True


def menu_item_embedding_text(item: MenuItem) -> str:
    """Compose the text we embed for semantic search of a dish."""
    parts = [
        item.name,
        item.category,
        item.spice_level,
        " ".join(item.dietary) if item.dietary else None,
        item.taste_profile,
        item.description,
        item.how_its_made,
    ]
    return " — ".join(p for p in parts if p)


class MenuService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MenuRepo(db)

    def list_items(self, include_unavailable: bool = False) -> list[MenuItem]:
        items = self.repo.list_all(include_unavailable=include_unavailable)
        if include_unavailable:
            return items  # admin sees everything (incl. 86'd / out-of-stock)
        return [i for i in items if effective_available(i)]

    def get_item(self, item_id: str, include_unavailable: bool = False) -> MenuItem:
        item = self.repo.get_by_id(item_id)
        if not item:
            raise ValueError(f"Menu item '{item_id}' not found")
        if not include_unavailable and not effective_available(item):
            raise ValueError(f"Menu item '{item_id}' not found")
        return item

    def find_by_name(self, query: str) -> list[MenuItem]:
        return self.repo.find_by_name(query)

    def search(self, query: str) -> list[MenuItem]:
        """Hybrid search: keyword ranking blended with semantic similarity
        (pgvector). Falls back to keyword-only when embeddings are
        unavailable. Customer-facing → only orderable dishes."""
        return [i for i in self.repo.hybrid_search(query) if effective_available(i)]

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
        items = self.repo.filter_items(
            category=category,
            dietary=dietary,
            spice_level=spice_level,
            max_price=max_price,
            keyword=keyword,
        )
        return [i for i in items if effective_available(i)]

    def create_item(self, **kwargs) -> MenuItem:
        item = self.repo.create(**kwargs)
        self._embed_item(item)
        return item

    def update_item(self, item_id: str, **kwargs) -> MenuItem:
        item = self.repo.update(item_id, **kwargs)
        if not item:
            raise ValueError(f"Menu item '{item_id}' not found")
        # Re-embed if any content field changed (cheap to always refresh).
        self._embed_item(item)
        return item

    def disable_item(self, item_id: str) -> None:
        if not self.repo.update(item_id, available=False):
            raise ValueError(f"Menu item '{item_id}' not found")

    # --- Embeddings ---

    def _embed_item(self, item: MenuItem) -> None:
        """Compute and store the dish's embedding. No-op if embeddings are off."""
        if not embeddings_enabled():
            return
        vec = embed_text(menu_item_embedding_text(item))
        if vec is not None:
            item.embedding = vec
            self.db.flush()

    def reembed_all(self, only_missing: bool = False) -> int:
        """(Re)generate embeddings for all items in one batch. Returns count
        embedded. Safe no-op when embeddings are disabled."""
        if not embeddings_enabled():
            return 0
        items = self.repo.list_all(include_unavailable=True)
        targets = [i for i in items if not only_missing or i.embedding is None]
        if not targets:
            return 0
        vecs = embed_texts([menu_item_embedding_text(i) for i in targets])
        if vecs is None:
            return 0
        for item, vec in zip(targets, vecs):
            item.embedding = vec
        self.db.flush()
        return len(targets)
