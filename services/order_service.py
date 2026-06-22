"""Order service: cart lifecycle and item management."""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.order import Order
from db.repositories.chat_repo import ChatRepo
from db.repositories.menu_repo import MenuRepo
from db.repositories.order_repo import OrderRepo
from services import order_lifecycle as lifecycle
from services.billing import compute_bill


class OrderService:
    def __init__(self, db: Session):
        self.db = db
        self.order_repo = OrderRepo(db)
        self.menu_repo = MenuRepo(db)
        self.chat_repo = ChatRepo(db)

    def get_or_create_cart(self, user_id: str) -> Order:
        cart = self.order_repo.get_cart_for_user(user_id)
        if cart:
            return cart
        cart = self.order_repo.create(user_id=user_id)
        self.chat_repo.create_session(order_id=cart.id, user_id=user_id)
        return cart

    def get_or_create_cart_for_customer(self, customer_id: str) -> Order:
        """Parcel-flow cart, keyed to an (auth-free) customer record."""
        cart = self.order_repo.get_cart_for_customer(customer_id)
        if cart:
            return cart
        try:
            cart = self.order_repo.create(customer_id=customer_id)
            self.chat_repo.create_session(order_id=cart.id, customer_id=customer_id)
            return cart
        except IntegrityError:
            # Lost the create race (uq_cart_per_customer) — return the winner.
            self.db.rollback()
            won = self.order_repo.get_cart_for_customer(customer_id)
            if won:
                return won
            raise

    def get_or_create_cart_for_table(
        self,
        table_id: str,
        zone_name: str | None = None,
        is_ac: bool = False,
        floor_name: str | None = None,
    ) -> Order:
        """Dine-in cart bound to a table's running tab (TableSession).

        Lazily opens the table session on the first round so a guest who scans
        but never orders doesn't occupy a table. Returns the open cart-status
        order for the table; subsequent rounds create fresh carts under the same
        session.
        """
        from db.repositories.table_repo import TableRepo
        from db.repositories.table_session_repo import TableSessionRepo

        cart = self.order_repo.get_cart_for_table(table_id)
        if cart:
            return cart

        ts_repo = TableSessionRepo(self.db)
        try:
            sess = ts_repo.get_open_for_table(table_id) or ts_repo.create(table_id=table_id)
            TableRepo(self.db).update(table_id, status="occupied")
            cart = self.order_repo.create(
                order_type=lifecycle.DINE_IN,
                table_id=table_id,
                table_session_id=sess.id,
                zone_name=zone_name,
                floor_name=floor_name,
                is_ac=is_ac,
            )
            self.chat_repo.create_session(order_id=cart.id)
            return cart
        except IntegrityError:
            # Lost a race on the open-session or cart unique index — return the
            # cart the winning request created for this table.
            self.db.rollback()
            won = self.order_repo.get_cart_for_table(table_id)
            if won:
                return won
            raise

    def settle_table_session(self, table_session_id: str) -> list[Order]:
        """Close out a dine-in table: pay every fired round, cancel any un-fired
        cart, close the session and free the table. Returns the settled orders.

        This is the deliberate "close the check" action, so it pays confirmed/
        cooking/served rounds directly rather than stepping each through the
        kitchen lifecycle.
        """
        from db.repositories.table_repo import TableRepo
        from db.repositories.table_session_repo import TableSessionRepo

        ts_repo = TableSessionRepo(self.db)
        sess = ts_repo.get_by_id(table_session_id)
        if not sess:
            raise ValueError("Table session not found")

        now = datetime.utcnow()
        settled: list[Order] = []
        for o in self.order_repo.list_for_table_session(table_session_id):
            if o.status == "cart":
                o.status = "cancelled"  # un-fired round — drop it
                self._close_chat(o.id)
            elif o.status not in lifecycle.CLOSED_STATUSES:
                if o.charges_json is None or o.total is None:
                    self._freeze_bill(o)
                o.status = "paid"
                if o.paid_at is None:
                    o.paid_at = now
                self._close_chat(o.id)
                settled.append(o)

        sess.status = "closed"
        sess.closed_at = now
        if sess.table_id:
            TableRepo(self.db).update(sess.table_id, status="free")
        self.db.flush()
        return settled

    def request_bill(self, table_session_id: str) -> None:
        """Mark a dine-in table session as bill-requested + flag the table."""
        from db.repositories.table_repo import TableRepo
        from db.repositories.table_session_repo import TableSessionRepo

        ts_repo = TableSessionRepo(self.db)
        sess = ts_repo.get_by_id(table_session_id)
        if not sess:
            raise ValueError("No open table session")
        if sess.status == "open":
            sess.status = "billed"
        if sess.table_id:
            TableRepo(self.db).update(sess.table_id, status="needs_bill")
        self.db.flush()

    def _assert_mutable(self, order_id: str) -> None:
        """Items may only be changed while the order is still a cart."""
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        if order.status != "cart":
            raise ValueError(
                f"Cannot change items on a '{order.status}' order — it has "
                "already been sent to the kitchen."
            )

    def add_item(
        self,
        order_id: str,
        menu_item_id: str,
        quantity: int = 1,
        special_instructions: str = "",
    ):
        self._assert_mutable(order_id)
        menu_item = self.menu_repo.get_by_id(menu_item_id)
        if not menu_item:
            raise ValueError(f"Menu item '{menu_item_id}' not found")
        if not menu_item.available:
            raise ValueError(f"'{menu_item.name}' is currently unavailable")
        return self.order_repo.add_item(
            order_id=order_id,
            menu_item_id=menu_item_id,
            quantity=quantity,
            price_at_order=float(menu_item.price),
            special_instructions=special_instructions,
        )

    def remove_item(self, order_id: str, menu_item_id: str) -> None:
        self._assert_mutable(order_id)
        if not self.order_repo.remove_item(order_id, menu_item_id):
            raise ValueError(f"Item '{menu_item_id}' not found in order")

    def set_item_quantity(
        self, order_id: str, menu_item_id: str, quantity: int
    ):
        """Set the ABSOLUTE quantity of an item (not a delta).

        quantity <= 0 removes the line. If the item isn't in the order yet it's
        added at the requested quantity.
        """
        self._assert_mutable(order_id)
        if quantity <= 0:
            self.order_repo.remove_item(order_id, menu_item_id)
            return None
        menu_item = self.menu_repo.get_by_id(menu_item_id)
        if not menu_item:
            raise ValueError(f"Menu item '{menu_item_id}' not found")
        if not menu_item.available:
            raise ValueError(f"'{menu_item.name}' is currently unavailable")
        existing = self.order_repo.get_item_in_order(order_id, menu_item_id)
        if existing:
            existing.quantity = quantity
            self.db.flush()
            return existing
        return self.order_repo.add_item(
            order_id=order_id,
            menu_item_id=menu_item_id,
            quantity=quantity,
            price_at_order=float(menu_item.price),
        )

    def _freeze_bill(self, order: Order) -> None:
        """Snapshot the bill onto the order so totals never drift later."""
        from decimal import Decimal

        from services.money import money_float
        subtotal = money_float(
            sum((Decimal(str(i.price_at_order)) * i.quantity for i in order.items), Decimal(0))
        )
        bill = compute_bill(
            subtotal,
            order_type=order.order_type or lifecycle.PARCEL,
            is_ac=bool(order.is_ac),
        )
        order.charges_json = bill["charges"]
        order.total = bill["total"]

    def confirm_order(self, order_id: str, customer=None) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        lifecycle.assert_transition(order.order_type or lifecycle.PARCEL, order.status, "confirmed")
        if not order.items:
            raise ValueError("Cannot confirm an empty order")
        order.status = "confirmed"
        order.confirmed_at = datetime.utcnow()

        # Parcel orders are never in an AC zone — guard so the dine-in AC
        # surcharge can never leak onto a delivery bill.
        if (order.order_type or lifecycle.PARCEL) == lifecycle.PARCEL:
            order.is_ac = False

        # Freeze the bill snapshot (subtotal + charges + total) at confirm time.
        self._freeze_bill(order)

        # Parcel: freeze the delivery snapshot onto the order so it survives later
        # edits to the customer record, and bump the customer's order stats.
        if customer is not None:
            order.contact_name = customer.name
            order.contact_phone = customer.phone
            order.delivery_address = customer.address_line
            order.delivery_area = customer.area
            order.delivery_pincode = customer.pincode
            customer.order_count = (customer.order_count or 0) + 1
            customer.last_order_at = order.confirmed_at

        self.db.flush()
        return order

    def advance_status(self, order_id: str, to_status: str) -> Order:
        """Move an order to the next lifecycle status, validating the transition.

        Stamps the matching timestamp (served_at / ready_at / delivered_at /
        paid_at). On ``paid`` it also closes the chat session and, for dine-in,
        the table session + frees the table.
        """
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        order_type = order.order_type or lifecycle.PARCEL
        lifecycle.assert_transition(order_type, order.status, to_status)
        order.status = to_status

        ts_col = lifecycle.STATUS_TIMESTAMP.get(to_status)
        if ts_col and getattr(order, ts_col) is None:
            setattr(order, ts_col, datetime.utcnow())

        if to_status == "paid":
            self._on_paid(order)
        elif to_status == "cancelled":
            self._close_chat(order_id)
            self._release_table_if_done(order)

        self.db.flush()
        return order

    def _close_chat(self, order_id: str) -> None:
        session = self.chat_repo.get_session_for_order(order_id)
        if session and session.status != "closed":
            session.status = "closed"
            session.closed_at = datetime.utcnow()
            self.db.flush()

    def _release_table_if_done(self, order: Order) -> None:
        """Dine-in: when an order leaves the floor (paid OR cancelled) and no
        other open orders remain on its table session, close the session and
        free the table. Safe to call for parcel orders (no-op)."""
        if order.order_type != lifecycle.DINE_IN or not order.table_session_id:
            return
        from db.repositories.table_repo import TableRepo
        from db.repositories.table_session_repo import TableSessionRepo

        siblings = [
            o
            for o in self.order_repo.list_for_table_session(order.table_session_id)
            if o.id != order.id
        ]
        # Drop abandoned EMPTY carts (un-fired rounds with no items) so a guest
        # who scanned + opened a round but never ordered can't keep the table
        # "occupied" forever once the real round is paid. A cart WITH items is a
        # round still being built, so it legitimately keeps the table open.
        for o in siblings:
            if o.status == lifecycle.CART and not o.items:
                o.status = lifecycle.CANCELLED
                self._close_chat(o.id)
        open_others = [
            o for o in siblings if o.status not in lifecycle.CLOSED_STATUSES
        ]
        if open_others:
            return
        ts = TableSessionRepo(self.db).get_by_id(order.table_session_id)
        if ts and ts.status != "closed":
            ts.status = "closed"
            ts.closed_at = datetime.utcnow()
        if ts and ts.table_id:
            TableRepo(self.db).update(ts.table_id, status="free")
        self.db.flush()

    def _on_paid(self, order: Order) -> None:
        self._close_chat(order.id)
        self._release_table_if_done(order)

    def get_orders_for_customer(self, customer_id: str) -> list[Order]:
        return self.order_repo.get_all_for_customer(customer_id)

    def cancel_order(self, order_id: str) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        if order.status not in ("cart", "confirmed"):
            raise ValueError(f"Cannot cancel order with status '{order.status}'")
        order.status = "cancelled"
        self.db.flush()
        self._close_chat(order_id)
        self._release_table_if_done(order)  # dine-in: free the table on cancel
        return order

    def mark_awaiting_payment(self, order_id: str) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order or order.status != "confirmed":
            raise ValueError(f"Order must be in 'confirmed' status")
        order.status = "awaiting_payment"
        self.db.flush()
        return order

    def mark_paid(self, order_id: str) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order or order.status != "awaiting_payment":
            raise ValueError("Order must be in 'awaiting_payment' status")
        order.status = "paid"
        order.paid_at = datetime.utcnow()
        self.db.flush()
        session = self.chat_repo.get_session_for_order(order_id)
        if session:
            session.status = "closed"
            session.closed_at = datetime.utcnow()
            self.db.flush()
        return order

    def mark_payment_failed(self, order_id: str) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order or order.status != "awaiting_payment":
            raise ValueError("Order must be in 'awaiting_payment' status")
        order.status = "confirmed"
        self.db.flush()
        return order

    def get_orders(self, user_id: str) -> list[Order]:
        return self.order_repo.get_all_for_user(user_id)

    def get_order(self, order_id: str, user_id: str) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("Order not found")
        return order

    # --- Admin-scope helpers (skip ownership check) ---

    def list_orders_admin(self, statuses: list[str] | None = None) -> list[Order]:
        return self.order_repo.list_all(statuses=statuses)

    def get_order_admin(self, order_id: str) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        return order
