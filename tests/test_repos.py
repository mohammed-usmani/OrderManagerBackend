from db.models.user import User
from db.models.menu import MenuItem
from db.models.order import Order
from db.repositories.user_repo import UserRepo
from db.repositories.menu_repo import MenuRepo
from db.repositories.order_repo import OrderRepo
from db.repositories.chat_repo import ChatRepo


def _make_user(db, email="repo@test.com"):
    repo = UserRepo(db)
    return repo.create(email=email, hashed_password="hash", name="Test User")


def _make_menu_item(db, item_id="R01"):
    repo = MenuRepo(db)
    return repo.create(id=item_id, name="Repo Dish", category="mains", price=200.0)


def test_user_repo_create_and_fetch(db):
    repo = UserRepo(db)
    user = repo.create(email="u1@test.com", hashed_password="h", name="U1")
    assert repo.get_by_email("u1@test.com").id == user.id
    assert repo.email_exists("u1@test.com") is True
    assert repo.email_exists("nobody@test.com") is False


def test_menu_repo_list_filters_unavailable(db):
    repo = MenuRepo(db)
    repo.create(id="AV01", name="Available", category="starters", price=100.0, available=True)
    repo.create(id="UN01", name="Unavailable", category="starters", price=100.0, available=False)

    available = repo.list_all(include_unavailable=False)
    ids = [i.id for i in available]
    assert "AV01" in ids
    assert "UN01" not in ids

    all_items = repo.list_all(include_unavailable=True)
    ids_all = [i.id for i in all_items]
    assert "UN01" in ids_all


def test_order_repo_get_or_no_cart(db):
    user = _make_user(db, "order_repo@test.com")
    repo = OrderRepo(db)

    assert repo.get_cart_for_user(user.id) is None

    order = repo.create(user_id=user.id)
    assert repo.get_cart_for_user(user.id).id == order.id


def test_order_repo_add_item_accumulates_quantity(db):
    user = _make_user(db, "additem@test.com")
    menu_item = _make_menu_item(db, "AI01")
    order_repo = OrderRepo(db)
    order = order_repo.create(user_id=user.id)

    order_repo.add_item(order.id, menu_item.id, 1, 200.0)
    order_repo.add_item(order.id, menu_item.id, 2, 200.0)

    item = order_repo.get_item_in_order(order.id, menu_item.id)
    assert item.quantity == 3


def test_chat_repo_create_session_and_messages(db):
    user = _make_user(db, "chat_repo@test.com")
    order_repo = OrderRepo(db)
    order = order_repo.create(user_id=user.id)
    chat_repo = ChatRepo(db)

    session = chat_repo.create_session(user_id=user.id, order_id=order.id)
    assert session.status == "active"

    chat_repo.add_message(session.id, "user", "Hello")
    chat_repo.add_message(session.id, "assistant", "Welcome!")

    msgs = chat_repo.get_messages(session.id)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
