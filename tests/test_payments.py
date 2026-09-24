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


# --- amount-due rules: what's due = everything fired − what's already paid ---

import pytest

from services import payment_service as payment_mod
from services.table_service import TableService
from services.zone_service import ZoneService


@pytest.fixture
def fake_razorpay(monkeypatch):
    """Stand-in for Razorpay: checkout creation and signature checks succeed."""
    counter = iter(range(1, 10_000))

    def create(amount, receipt):
        return {"id": f"order_fake_{next(counter)}", "amount": int(round(amount * 100))}

    monkeypatch.setattr(payment_mod, "create_razorpay_order", create)
    monkeypatch.setattr(payment_mod, "verify_payment_signature", lambda *a: True)


def _dish(db, price=300.0):
    mi = MenuItem(id=f"D{uuid.uuid4().hex[:5]}", name="Dish", category="mains", price=price, available=True)
    db.add(mi)
    db.flush()
    return mi


def _table_session(db):
    """Non-AC dine-in table with one fired round; returns (svc, table, zone, first_round)."""
    zone = ZoneService(db).create_zone(name=f"Z-{uuid.uuid4().hex[:5]}", is_ac=False)
    table = TableService(db).create_table(zone_id=zone.id, label=uuid.uuid4().hex[:4], seats=4)
    svc = OrderService(db)
    r1 = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=False)
    svc.add_item(r1.id, _dish(db).id, 1)
    svc.confirm_order(r1.id)
    return svc, table, zone, r1


def _fire_round(db, svc, table, zone):
    r = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=False)
    svc.add_item(r.id, _dish(db).id, 1)
    svc.confirm_order(r.id)
    return r


def test_negative_tip_is_rejected(db):
    cart = _order(db)
    with pytest.raises(ValueError, match="[Tt]ip"):
        PaymentService(db).amount_due(order_id=cart.id, tip=-10)


def test_discount_cannot_exceed_the_bill(db):
    cart = _order(db)
    base = PaymentService(db).amount_due(order_id=cart.id)
    with pytest.raises(ValueError, match="[Dd]iscount"):
        PaymentService(db).settle_cash(order_id=cart.id, discount=base + 1)


def test_paid_order_cannot_be_paid_again(db):
    cart = _order(db)
    PaymentService(db).settle_cash(order_id=cart.id)
    with pytest.raises(ValueError, match="already paid|[Nn]othing"):
        PaymentService(db).settle_cash(order_id=cart.id)
    assert db.query(Payment).filter(Payment.order_id == cart.id).count() == 1


def test_unconfirmed_cart_cannot_be_paid(db):
    user = UserService(db).register(f"{uuid.uuid4()}@t.com", "pass", "T")
    o = OrderService(db)
    cart = o.get_or_create_cart(user.id)
    o.add_item(cart.id, _dish(db).id, 1)
    with pytest.raises(ValueError):
        PaymentService(db).settle_cash(order_id=cart.id)
    assert cart.status == "cart"


def test_closed_tab_cannot_be_charged(db, fake_razorpay):
    svc, table, zone, r1 = _table_session(db)
    PaymentService(db).settle_cash(session_id=r1.table_session_id)
    with pytest.raises(ValueError):
        PaymentService(db).create_checkout(session_id=r1.table_session_id)


def test_unfired_round_is_not_billed(db):
    svc, table, zone, r1 = _table_session(db)
    cart = svc.get_or_create_cart_for_table(table.id, zone_name=zone.name, is_ac=False)
    svc.add_item(cart.id, _dish(db, 999.0).id, 1)  # in the cart, never sent to the kitchen
    assert PaymentService(db).amount_due(session_id=r1.table_session_id) == float(r1.total)


def test_stale_checkout_only_pays_what_it_covered(db, fake_razorpay):
    svc, table, zone, r1 = _table_session(db)
    sid = r1.table_session_id
    pay = PaymentService(db)
    checkout = pay.create_checkout(session_id=sid)  # covers round 1 only
    r2 = _fire_round(db, svc, table, zone)          # ordered after the checkout was opened

    pay.confirm_razorpay(provider_order_id=checkout["provider_order_id"],
                         razorpay_payment_id="pay_1", signature="sig")

    detail = TableService(db).session_detail(sid)
    assert detail["status"] != "closed"                      # tab stays open
    assert pay.amount_due(session_id=sid) == float(r2.total)  # only round 2 still owed

    pay.settle_cash(session_id=sid)                          # pay the rest
    assert TableService(db).session_detail(sid)["status"] == "closed"


def test_razorpay_confirmation_is_idempotent(db, fake_razorpay):
    cart = _order(db)
    pay = PaymentService(db)
    checkout = pay.create_checkout(order_id=cart.id)
    for _ in range(2):  # webhook and client callback both arrive
        pay.confirm_razorpay(provider_order_id=checkout["provider_order_id"],
                             razorpay_payment_id="pay_1", signature="sig")
    assert db.query(Payment).filter(Payment.status == "paid").count() == 1
    assert cart.status == "paid"


# --- router: discounts are staff-only ---

from fastapi.testclient import TestClient

from db.base import get_db
from services.auth_service import auth_service


@pytest.fixture
def client(db, fake_razorpay, monkeypatch):
    from main import app
    from routers import payments as payments_router

    monkeypatch.setattr(payments_router, "razorpay_enabled", lambda: True)
    app.dependency_overrides[get_db] = _yield_db(db)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _yield_db(db):
    def override():
        yield db
    return override


def _token(db, role):
    u = UserService(db).register(f"{uuid.uuid4()}@t.com", "pass", "Staff", role=role)
    return auth_service.create_access_token(u.id, u.email, u.is_admin, role=role)


def test_guest_checkout_cannot_apply_a_discount(client, db):
    cart = _order(db)
    r = client.post("/payments/razorpay/order", json={"order_id": cart.id, "discount": 150})
    assert r.status_code == 403


def test_guest_checkout_can_add_a_tip(client, db):
    cart = _order(db)
    r = client.post("/payments/razorpay/order", json={"order_id": cart.id, "tip": 20})
    assert r.status_code == 200


def test_cashier_checkout_can_apply_a_discount(client, db):
    cart = _order(db)
    headers = {"Authorization": f"Bearer {_token(db, 'cashier')}"}
    r = client.post("/payments/razorpay/order", json={"order_id": cart.id, "discount": 50}, headers=headers)
    assert r.status_code == 200


def test_guest_quote_cannot_apply_a_discount(client, db):
    cart = _order(db)
    r = client.post("/payments/quote", json={"order_id": cart.id, "discount": 150})
    assert r.status_code == 403
