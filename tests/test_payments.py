import uuid

from db.models.menu import MenuItem
from db.models.payment import Payment
from services.order_service import OrderService
from services.payment_service import PaymentService
from services.payments import verify_payment_signature
from services.user_service import UserService


def _order(db):
    user = UserService(db).register(f"{uuid.uuid4()}@t.com", "pass", "T")
    db.add(MenuItem(id=f"P{uuid.uuid4().hex[:4]}", name="Dish", category="mains", price=200.0, available=True))
    db.flush()
    mi = db.query(MenuItem).order_by(MenuItem.created_at.desc()).first()
    o = OrderService(db)
    cart = o.get_or_create_cart(user.id)
    o.add_item(cart.id, mi.id, quantity=1)
    o.confirm_order(cart.id)
    return cart


def test_cash_settle_marks_paid_and_records_payment(db):
    cart = _order(db)
    pay = PaymentService(db).settle_cash(order_id=cart.id, tip=20, discount=0)
    assert pay.status == "paid" and pay.method == "cash"
    assert cart.status == "paid"
    assert cart.payment_method == "cash"
    assert float(cart.tip_amount) == 20
    assert db.query(Payment).count() == 1


def test_amount_due_applies_tip_and_discount(db):
    cart = _order(db)
    base = PaymentService(db).amount_due(order_id=cart.id)
    withtip = PaymentService(db).amount_due(order_id=cart.id, tip=50, discount=10)
    assert round(withtip - base) == 40


def test_signature_verification_rejects_forgery():
    # Without the real secret a forged signature must not verify.
    assert verify_payment_signature("order_x", "pay_y", "deadbeef") is False
