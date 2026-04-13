from db.seeds.menu_seed import seed_menu, seed_admin
from services.menu_service import MenuService
from db.repositories.user_repo import UserRepo
from db.models.menu import MenuItem
from agent.restaurant.menu import MENU

_EXPECTED_MENU_COUNT = sum(len(v) for v in MENU.values())


def _clear_menu(db):
    db.query(MenuItem).delete()
    db.flush()


def test_seed_menu_populates_all_items(db):
    _clear_menu(db)
    seed_menu(db)
    service = MenuService(db)
    items = service.list_items(include_unavailable=True)
    assert len(items) == _EXPECTED_MENU_COUNT


def test_seed_menu_is_idempotent(db):
    _clear_menu(db)
    seed_menu(db)
    seed_menu(db)  # second call should be a no-op
    service = MenuService(db)
    items = service.list_items(include_unavailable=True)
    assert len(items) == _EXPECTED_MENU_COUNT


def test_seed_admin_creates_admin_user(db):
    seed_admin(db, email="admin@test.com", password="adminpass")
    repo = UserRepo(db)
    user = repo.get_by_email("admin@test.com")
    assert user is not None
    assert user.is_admin is True


def test_seed_admin_is_idempotent(db):
    seed_admin(db, email="admin2@test.com", password="pass")
    seed_admin(db, email="admin2@test.com", password="pass")  # no-op
    repo = UserRepo(db)
    from db.models.user import User
    count = db.query(User).filter(User.email == "admin2@test.com").count()
    assert count == 1
