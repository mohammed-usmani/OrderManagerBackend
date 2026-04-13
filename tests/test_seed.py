from db.seeds.menu_seed import seed_menu, seed_admin
from services.menu_service import MenuService
from db.repositories.user_repo import UserRepo


def test_seed_menu_populates_all_items(db):
    seed_menu(db)
    service = MenuService(db)
    items = service.list_items(include_unavailable=True)
    assert len(items) == 27


def test_seed_menu_is_idempotent(db):
    seed_menu(db)
    seed_menu(db)  # second call should be a no-op
    service = MenuService(db)
    items = service.list_items(include_unavailable=True)
    assert len(items) == 27


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
