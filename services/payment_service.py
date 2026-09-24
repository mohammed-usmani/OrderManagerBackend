"""Payment orchestration: settle an order or a table session via cash/Razorpay.

Payment is treated as orthogonal to fulfilment — settling records a Payment row
and then closes out the target (session settle, or advancing a delivered parcel
order to paid). Tips/discounts are captured on the Payment (and mirrored onto the
order for single-order settlements).

What's due is always "everything fired for the target − what paid payments have
already covered". A checkout therefore pays only what was due when it was
opened: rounds ordered afterwards stay owed, a paid bill can't be paid again,
and the target closes only once nothing is left. Payment writes lock the target
row so concurrent settles (double-clicks, webhook + callback) run one at a time.
"""

from decimal import Decimal

from config import RAZORPAY_KEY_ID
from db.models.order import Order
from db.models.payment import Payment
from db.models.table_session import TableSession
from db.repositories.order_repo import OrderRepo
from services.billing import bill_for_order
from services.audit_service import write_audit
from services.money import money_float, to_money
from services.order_service import OrderService
from services.payments import create_razorpay_order, verify_payment_signature

# Rounds that were never sent to the kitchen, or were cancelled, aren't billed.
_UNBILLED = {"cart", "cancelled"}
_SETTLED = Decimal("0.005")


def _reason(discount, reason) -> str | None:
    """A discount's reason, kept only when there is a discount."""
    return (reason or "").strip() or None if discount else None


class PaymentService:
    def __init__(self, db):
        self.db = db
        self.orders = OrderService(db)

    # --- amount ---

    def _target(self, order_id, session_id, *, lock: bool):
        """The session or order being paid, validated as still payable."""
        model, key = (TableSession, session_id) if session_id else (Order, order_id)
        if not key:
            raise ValueError("Nothing to pay for")
        query = self.db.query(model).filter(model.id == key)
        if lock:
            query = query.with_for_update()
        target = query.first()
        if target is None:
            raise ValueError("Table session not found" if session_id else "Order not found")
        if session_id and target.status == "closed":
            raise ValueError("This table's bill is already closed")
        if order_id and target.status in _UNBILLED:
            raise ValueError("This order hasn't been placed yet" if target.status == "cart"
                             else "This order was cancelled")
        if order_id and target.status == "paid":
            raise ValueError("This order is already paid")
        return target

    def _billed(self, order_id, session_id) -> Decimal:
        if session_id:
            # Rounds already paid on their own (by order) aren't owed again at the table.
            orders = OrderRepo(self.db).list_for_table_session(session_id)
            skip = _UNBILLED | {"paid"}
        else:
            orders = [OrderRepo(self.db).get_by_id(order_id)]
            skip = _UNBILLED
        return sum(
            (to_money(bill_for_order(o)["total"]) for o in orders if o.status not in skip),
            Decimal(0),
        )

    def _still_open(self, pay: Payment) -> bool:
        """Lock the payment's target and report whether it can still be closed.
        A late online payment can land after the table was settled another way
        (and a new party seated): it must not close anything again."""
        if pay.table_session_id:
            sess = (self.db.query(TableSession).filter(TableSession.id == pay.table_session_id)
                    .with_for_update().first())
            return sess is not None and sess.status != "closed"
        order = self.db.query(Order).filter(Order.id == pay.order_id).with_for_update().first()
        return order is not None and order.status not in ("paid", "cancelled")

    def _covered(self, order_id, session_id) -> Decimal:
        """Bill amount already covered by paid payments (tips aside, discounts included)."""
        column = Payment.table_session_id if session_id else Payment.order_id
        paid = self.db.query(Payment).filter(column == (session_id or order_id),
                                             Payment.status == "paid")
        return sum(
            (to_money(p.amount) - to_money(p.tip_amount) + to_money(p.discount_amount) for p in paid),
            Decimal(0),
        )

    def _due(self, order_id, session_id) -> Decimal:
        return self._billed(order_id, session_id) - self._covered(order_id, session_id)

    def _target_amount(self, order_id, session_id, tip, discount, *, lock: bool = False):
        tipm, discm = to_money(tip or 0), to_money(discount or 0)
        if tipm < 0:
            raise ValueError("Tip can't be negative")
        if discm < 0:
            raise ValueError("Discount can't be negative")
        self._target(order_id, session_id, lock=lock)
        due = self._due(order_id, session_id)
        if due < _SETTLED:
            raise ValueError("Nothing left to pay — this bill is already paid")
        if discm > due:
            raise ValueError("Discount can't be more than the amount due")
        receipt = f"sess-{session_id[:8]}" if session_id else f"ord-{order_id[:8]}"
        return money_float(due + tipm - discm), receipt

    def amount_due(self, *, order_id=None, session_id=None, tip=0, discount=0) -> float:
        return self._target_amount(order_id, session_id, tip, discount)[0]

    # --- checkout (Razorpay) ---

    def create_checkout(self, *, order_id=None, session_id=None, tip=0, discount=0,
                        discount_reason=None) -> dict:
        amount, receipt = self._target_amount(order_id, session_id, tip, discount, lock=True)
        ro = create_razorpay_order(amount, receipt)
        pay = Payment(
            order_id=order_id, table_session_id=session_id,
            method="razorpay", provider="razorpay", provider_order_id=ro["id"],
            amount=amount, tip_amount=to_money(tip or 0), discount_amount=to_money(discount or 0),
            discount_reason=_reason(discount, discount_reason), status="created",
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
            .with_for_update()  # webhook and client callback may arrive together
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

    def settle_cash(self, *, order_id=None, session_id=None, tip=0, discount=0,
                    discount_reason=None, actor=None) -> Payment:
        amount, _ = self._target_amount(order_id, session_id, tip, discount, lock=True)
        pay = Payment(
            order_id=order_id, table_session_id=session_id, method="cash",
            amount=amount, tip_amount=to_money(tip or 0), discount_amount=to_money(discount or 0),
            discount_reason=_reason(discount, discount_reason), status="paid",
        )
        self.db.add(pay)
        self.db.flush()
        self._finalize(pay, actor)
        return pay

    def _finalize(self, pay: Payment, actor) -> None:
        # Close the target only once this payment leaves nothing owed. A stale
        # checkout (rounds added after it opened) stays a partial payment.
        open_target = self._still_open(pay)
        due = self._due(pay.order_id, pay.table_session_id)
        fully_paid = open_target and due < _SETTLED
        # Money received for a target that was already paid or closed: keep the
        # record (it was captured) and flag it for a refund in the audit log.
        overpaid = not open_target or due <= -_SETTLED
        if pay.table_session_id and fully_paid:
            settled = self.orders.settle_table_session(pay.table_session_id)
            for o in settled:
                o.payment_method = pay.method
        elif pay.order_id and fully_paid:
            order = self.orders.get_order_admin(pay.order_id)
            order.tip_amount = pay.tip_amount
            order.discount_amount = pay.discount_amount
            order.discount_reason = pay.discount_reason
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
                  "discount": float(pay.discount_amount), "discount_reason": pay.discount_reason,
                  "overpaid": overpaid,
                  "order_id": pay.order_id, "table_session_id": pay.table_session_id},
        )
        self.db.flush()
