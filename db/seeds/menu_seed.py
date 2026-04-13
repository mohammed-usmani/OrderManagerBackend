"""Seed the database from the hardcoded menu in agent/restaurant/menu.py."""

from sqlalchemy.orm import Session

from agent.restaurant.menu import MENU
from db.repositories.menu_repo import MenuRepo
from db.repositories.user_repo import UserRepo
from services.user_service import UserService


def seed_menu(db: Session) -> None:
    """Populate menu_items from MENU dict. No-op if already seeded."""
    repo = MenuRepo(db)
    if repo.count() > 0:
        return

    category_map = {
        "starters": "starters",
        "mains": "mains",
        "breads": "breads",
        "rice": "rice",
        "desserts": "desserts",
        "beverages": "beverages",
    }

    for category_key, items in MENU.items():
        category = category_map.get(category_key, category_key)
        for item in items:
            repo.create(
                id=item["id"],
                name=item["name"],
                description=item.get("description"),
                how_its_made=item.get("how_its_made"),
                taste_profile=item.get("taste_profile"),
                category=category,
                price=float(item["price"]),
                currency=item.get("currency", "INR"),
                serving=item.get("serving"),
                dietary=item.get("dietary"),
                spice_level=item.get("spice_level"),
                popularity=item.get("popularity"),
                popularity_note=item.get("popularity_note"),
                available=item.get("available", True),
            )


def seed_admin(db: Session, email: str, password: str) -> None:
    """Create the admin user if they don't already exist."""
    repo = UserRepo(db)
    if repo.email_exists(email):
        return
    UserService(db).register(email=email, password=password, name="Admin", is_admin=True)
