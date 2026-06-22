import pytest
from services.order_service import OrderService
from services.user_service import UserService
from db.models.menu import MenuItem
import uuid


def _make_user(db):
    s = UserService(db)
    return s.register(f"{uuid.uuid4()}@test.com", "pass", "Test")


def _make_menu_item(db, item_id="OS01"):
    item = MenuItem(id=item_id, name="Order Item", category="mains", price=300.0, available=True)
    db.add(item)
    db.flush()
    return item


def test_get_or_create_cart_creates_once(db):
    user = _make_user(db)
    service = OrderService(db)
    cart1 = service.get_or_create_cart(user.id)
    cart2 = service.get_or_create_cart(user.id)
    assert cart1.id == cart2.id
    assert cart1.status == "cart"


def test_add_item_to_cart(db):
    user = _make_user(db)
    menu_item = _make_menu_item(db, "OS02")
    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)

    oi = service.add_item(cart.id, "OS02", quantity=2)
    assert oi.quantity == 2
    assert float(oi.price_at_order) == 300.0


def test_add_unavailable_item_raises(db):
    user = _make_user(db)
    item = MenuItem(id="OS03", name="Gone", category="mains", price=100.0, available=False)
    db.add(item)
    db.flush()

    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)
    with pytest.raises(ValueError, match="unavailable"):
        service.add_item(cart.id, "OS03", quantity=1)


def test_remove_item(db):
    user = _make_user(db)
    menu_item = _make_menu_item(db, "OS04")
    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)
    service.add_item(cart.id, "OS04", quantity=1)
    service.remove_item(cart.id, "OS04")

    from db.repositories.order_repo import OrderRepo
    assert OrderRepo(db).get_item_in_order(cart.id, "OS04") is None


def test_confirm_order(db):
    user = _make_user(db)
    menu_item = _make_menu_item(db, "OS05")
    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)
    service.add_item(cart.id, "OS05", quantity=1)

    confirmed = service.confirm_order(cart.id)
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_at is not None


def test_cancel_order_closes_session(db):
    user = _make_user(db)
    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)

    cancelled = service.cancel_order(cart.id)
    assert cancelled.status == "cancelled"

    from db.repositories.chat_repo import ChatRepo
    session = ChatRepo(db).get_session_for_order(cart.id)
    assert session.status == "closed"


def test_void_item_excludes_from_bill(db):
    user = _make_user(db)
    _make_menu_item(db, "OS07")
    _make_menu_item(db, "OS08")
    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)
    service.add_item(cart.id, "OS07", quantity=1)  # 300
    service.add_item(cart.id, "OS08", quantity=1)  # 300
    service.confirm_order(cart.id)
    before = float(cart.total)
    # Void one of the two lines.
    item = next(i for i in cart.items if i.menu_item_id == "OS08")
    service.void_item(cart.id, item.id, reason="kitchen ran out")
    assert item.status == "voided"
    assert float(cart.total) < before  # bill re-frozen without the voided line


def test_refund_only_paid(db):
    user = _make_user(db)
    _make_menu_item(db, "OS09")
    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)
    service.add_item(cart.id, "OS09", quantity=1)
    service.confirm_order(cart.id)
    with pytest.raises(ValueError, match="paid order"):
        service.refund_order(cart.id, reason="x")
    # March to paid, then refund.
    for s in ("cooking", "ready", "delivered", "paid"):
        service.advance_status(cart.id, s)
    refunded = service.refund_order(cart.id, reason="customer complaint")
    assert refunded.refunded is True and refunded.refund_reason == "customer complaint"


def test_payment_failure_keeps_session_active(db):
    user = _make_user(db)
    menu_item = _make_menu_item(db, "OS06")
    service = OrderService(db)
    cart = service.get_or_create_cart(user.id)
    service.add_item(cart.id, "OS06", quantity=1)
    service.confirm_order(cart.id)
    service.mark_awaiting_payment(cart.id)

    order = service.mark_payment_failed(cart.id)
    assert order.status == "confirmed"

    from db.repositories.chat_repo import ChatRepo
    session = ChatRepo(db).get_session_for_order(cart.id)
    assert session.status == "active"
