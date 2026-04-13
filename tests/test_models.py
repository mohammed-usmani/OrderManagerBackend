from datetime import datetime
from db.models.user import User
from db.models.menu import MenuItem
from db.models.order import Order, OrderItem
from db.models.chat import ChatSession, ChatMessage


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


def test_order_defaults(db):
    user = User(email="order_user@example.com", hashed_password="h", name="U")
    db.add(user)
    db.flush()

    order = Order(user_id=user.id)
    db.add(order)
    db.flush()

    assert order.id is not None
    assert order.status == "cart"
    assert order.confirmed_at is None


def test_order_item_price_snapshot(db):
    user = User(email="item_user@example.com", hashed_password="h", name="U")
    item = MenuItem(id="T02", name="Snap Dish", category="mains", price=500.0)
    db.add_all([user, item])
    db.flush()

    order = Order(user_id=user.id)
    db.add(order)
    db.flush()

    oi = OrderItem(
        order_id=order.id,
        menu_item_id=item.id,
        quantity=2,
        price_at_order=500.0,
    )
    db.add(oi)
    db.flush()

    # Simulate price change — snapshot is unaffected
    item.price = 600.0
    db.flush()

    fetched = db.get(OrderItem, oi.id)
    assert float(fetched.price_at_order) == 500.0


def test_chat_session_links_order(db):
    user = User(email="chat_user@example.com", hashed_password="h", name="U")
    db.add(user)
    db.flush()

    order = Order(user_id=user.id)
    db.add(order)
    db.flush()

    session = ChatSession(user_id=user.id, order_id=order.id)
    db.add(session)
    db.flush()

    msg = ChatMessage(session_id=session.id, role="user", content="Hello")
    db.add(msg)
    db.flush()

    assert session.status == "active"
    assert len(session.messages) == 1
    assert session.messages[0].content == "Hello"
