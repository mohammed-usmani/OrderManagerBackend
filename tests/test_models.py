from datetime import datetime
from db.models.user import User
from db.models.menu import MenuItem


def test_user_model_defaults(db):
    user = User(email="test@example.com", hashed_password="hash", name="Test")
    db.add(user)
    db.flush()

    assert user.id is not None
    assert user.is_admin is False
    assert isinstance(user.created_at, datetime)


def test_menu_item_model(db):
    item = MenuItem(
        id="T01",
        name="Test Dish",
        category="starters",
        price=100.0,
        available=True,
    )
    db.add(item)
    db.flush()

    fetched = db.get(MenuItem, "T01")
    assert fetched.name == "Test Dish"
    assert fetched.currency == "INR"
    assert fetched.available is True
