"""Seed the database from the hardcoded menu in agent/restaurant/menu.py."""

from sqlalchemy.orm import Session

from agent.restaurant.menu import IMAGE_URLS, MENU
from db.models.menu import MenuItem
from db.repositories.menu_repo import MenuRepo
from db.repositories.user_repo import UserRepo
from services.user_service import UserService


def seed_menu(db: Session) -> None:
    """Populate menu_items from MENU dict. Backfills image_url on rows that
    were seeded before image URLs existed."""
    repo = MenuRepo(db)

    if repo.count() == 0:
        for category_key, items in MENU.items():
            for item in items:
                repo.create(
                    id=item["id"],
                    name=item["name"],
                    description=item.get("description"),
                    how_its_made=item.get("how_its_made"),
                    taste_profile=item.get("taste_profile"),
                    category=category_key,
                    price=float(item["price"]),
                    currency=item.get("currency", "INR"),
                    serving=item.get("serving"),
                    dietary=item.get("dietary"),
                    spice_level=item.get("spice_level"),
                    popularity=item.get("popularity"),
                    popularity_note=item.get("popularity_note"),
                    image_url=IMAGE_URLS.get(item["id"]),
                    available=item.get("available", True),
                )
        return

    # Sync image_url on every startup so edits to IMAGE_URLS propagate
    # without a manual migration. Only touch rows where the DB value
    # differs from the map.
    changed = 0
    for row in db.query(MenuItem).all():
        desired = IMAGE_URLS.get(row.id)
        if desired and row.image_url != desired:
            row.image_url = desired
            changed += 1
    if changed:
        db.flush()


def seed_admin(db: Session, email: str, password: str) -> None:
    """Create the admin user if they don't already exist."""
    repo = UserRepo(db)
    if repo.email_exists(email):
        return
    UserService(db).register(email=email, password=password, name="Admin", role="owner")
