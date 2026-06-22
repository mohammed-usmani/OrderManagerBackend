"""Payment orchestration: settle an order or a table session via cash/Razorpay.

Payment is treated as orthogonal to fulfilment — settling records a Payment row
and then closes out the target (session settle, or advancing a delivered parcel
order to paid). Tips/discounts are captured on the Payment (and mirrored onto the
order for single-order settlements).
"""

from config import RAZORPAY_KEY_ID
from db.models.payment import Payment
from services.audit_service import write_audit
from services.money import money_float, to_money
from services.order_service import OrderService
from services.payments import create_razorpay_order, verify_payment_signature
from services.table_service import TableService


class PaymentService:
    def __init__(self, db):
        self.db = db
        self.orders = OrderService(db)

    # --- amount ---

    def _target_amount(self, order_id, session_id, tip, discount):
        tipm, discm = to_money(tip or 0), to_money(discount or 0)
        if session_id:
            detail = TableService(self.db).session_detail(session_id)
            base = to_money(detail["grand_total"])
            return money_float(base + tipm - discm), f"sess-{session_id[:8]}"
        if order_id:
            order = self.orders.get_order_admin(order_id)
            base = to_money(order.total or 0)
            return money_float(base + tipm - discm), f"ord-{order_id[:8]}"
        raise ValueError("Nothing to pay for")

    def amount_due(self, *, order_id=None, session_id=None, tip=0, discount=0) -> float:
        return self._target_amount(order_id, session_id, tip, discount)[0]

    # --- checkout (Razorpay) ---

    def create_checkout(self, *, order_id=None, session_id=None, tip=0, discount=0) -> dict:
        amount, receipt = self._target_amount(order_id, session_id, tip, discount)
        ro = create_razorpay_order(amount, receipt)
        pay = Payment(
            order_id=order_id, table_session_id=session_id,
            method="razorpay", provider="razorpay", provider_order_id=ro["id"],
            amount=amount, tip_amount=to_money(tip or 0), discount_amount=to_money(discount or 0),
            status="created",
        )
        self.db.add(pay)
        self.db.flush()
        return {
            "provider_order_id": ro["id"],
            "amount": amount,
            "amount_paise": ro["amount"],
            "currency": ro.get("currency", "INR"),
            "key_id": RAZORPAY_KEY_ID,
            "payment_id": pay.id,
        }

    def confirm_razorpay(self, *, provider_order_id, razorpay_payment_id, signature, actor=None) -> Payment:
        if not verify_payment_signature(provider_order_id, razorpay_payment_id, signature):
            raise ValueError("Payment signature verification failed")
        pay = (
            self.db.query(Payment)
            .filter(Payment.provider_order_id == provider_order_id)
            .first()
        )
        if not pay:
            raise ValueError("Payment record not found")
        if pay.status == "paid":
            return pay  # idempotent (webhook + callback can both arrive)
        pay.provider_payment_id = razorpay_payment_id
        pay.status = "paid"
        self.db.flush()
        self._finalize(pay, actor)
        return pay

    def settle_cash(self, *, order_id=None, session_id=None, tip=0, discount=0, actor=None) -> Payment:
        amount, _ = self._target_amount(order_id, session_id, tip, discount)
        pay = Payment(
            order_id=order_id, table_session_id=session_id, method="cash",
            amount=amount, tip_amount=to_money(tip or 0), discount_amount=to_money(discount or 0),
            status="paid",
        )
        self.db.add(pay)
        self.db.flush()
        self._finalize(pay, actor)
        return pay

    def _finalize(self, pay: Payment, actor) -> None:
        if pay.table_session_id:
            settled = self.orders.settle_table_session(pay.table_session_id)
            for o in settled:
                o.payment_method = pay.method
        elif pay.order_id:
            order = self.orders.get_order_admin(pay.order_id)
            order.tip_amount = pay.tip_amount
            order.discount_amount = pay.discount_amount
            order.payment_method = pay.method
            if order.status != "paid":
                # Payment is orthogonal to the kitchen flow — close it out.
                order.status = "paid"
                from datetime import datetime
                if order.paid_at is None:
                    order.paid_at = datetime.utcnow()
                self.orders._on_paid(order)
        self.db.flush()
        write_audit(
            self.db, actor=actor, action="payment.settle", entity="payment",
            entity_id=pay.id,
            meta={"method": pay.method, "amount": float(pay.amount),
                  "order_id": pay.order_id, "table_session_id": pay.table_session_id},
        )
        self.db.flush()
