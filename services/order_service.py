"""Order service: cart lifecycle and item management."""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.order import Order
from db.repositories.chat_repo import ChatRepo
from db.repositories.menu_repo import MenuRepo
from db.repositories.order_repo import OrderRepo
from services import order_lifecycle as lifecycle
from services.audit_service import write_audit
from services.billing import compute_bill
from services.events import publish_order_event
from services.menu_service import effective_available


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
        publish_order_event("settled", table_session_id=table_session_id)
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
        publish_order_event("bill_requested", table_session_id=table_session_id)

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
        if not effective_available(menu_item):
            raise ValueError(f"Sorry, '{menu_item.name}' just ran out / is unavailable")
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
        if not effective_available(menu_item):
            raise ValueError(f"Sorry, '{menu_item.name}' just ran out / is unavailable")
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
            sum(
                (Decimal(str(i.price_at_order)) * i.quantity
                 for i in order.items if i.status != "voided"),
                Decimal(0),
            )
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

        # Decrement tracked stock and auto-86 anything that hits zero.
        for it in order.items:
            mi = self.menu_repo.get_by_id(it.menu_item_id)
            if mi and mi.track_stock and mi.stock_qty is not None:
                mi.stock_qty = max(0, mi.stock_qty - it.quantity)
                if mi.stock_qty <= 0:
                    mi.is_86 = True

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
        publish_order_event("confirmed", order_id=order.id, status=order.status)
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
        publish_order_event("status", order_id=order.id, status=to_status)
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

    def cancel_order(self, order_id: str, reason: str | None = None, actor=None) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        if order.status not in ("cart", "confirmed", "cooking"):
            raise ValueError(f"Cannot cancel order with status '{order.status}'")
        order.status = "cancelled"
        if reason:
            order.cancellation_reason = reason
        self.db.flush()
        self._close_chat(order_id)
        self._release_table_if_done(order)  # dine-in: free the table on cancel
        write_audit(self.db, actor=actor, action="order.cancel", entity="order",
                    entity_id=order.id, reason=reason)
        publish_order_event("status", order_id=order.id, status="cancelled")
        return order

    # --- Order editing / void / refund / per-item status (admin) ---

    _EDITABLE_STATUSES = {"cart", "confirmed", "cooking"}

    def _assert_editable(self, order: Order) -> None:
        if order.status not in self._EDITABLE_STATUSES:
            raise ValueError(
                f"Can't edit a '{order.status}' order — it's already served/paid/closed."
            )

    def edit_item_admin(
        self, order_id: str, menu_item_id: str, quantity: int,
        special_instructions: str = "", actor=None,
    ) -> Order:
        """Add or set an item's quantity on an in-progress order, then re-freeze
        the bill. quantity<=0 removes the line."""
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        self._assert_editable(order)
        if quantity <= 0:
            self.order_repo.remove_item(order_id, menu_item_id)
        else:
            menu_item = self.menu_repo.get_by_id(menu_item_id)
            if not menu_item:
                raise ValueError(f"Menu item '{menu_item_id}' not found")
            existing = self.order_repo.get_item_in_order(order_id, menu_item_id)
            if existing:
                existing.quantity = quantity
                if special_instructions:
                    existing.special_instructions = special_instructions
            else:
                self.order_repo.add_item(
                    order_id=order_id, menu_item_id=menu_item_id, quantity=quantity,
                    price_at_order=float(menu_item.price),
                    special_instructions=special_instructions,
                )
        self.db.flush()
        self.db.refresh(order)
        if order.status != "cart":
            self._freeze_bill(order)
        write_audit(self.db, actor=actor, action="order.edit_item", entity="order",
                    entity_id=order.id, meta={"menu_item_id": menu_item_id, "quantity": quantity})
        self.db.flush()
        publish_order_event("edited", order_id=order.id, status=order.status)
        return order

    def void_item(self, order_id: str, order_item_id: str, reason: str, actor=None) -> Order:
        """Void a single line (kitchen can't make it / customer changed mind),
        keeping it on the ticket for the record but off the bill."""
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        item = next((i for i in order.items if i.id == order_item_id), None)
        if not item:
            raise ValueError("Line item not found on this order")
        item.status = "voided"
        item.void_reason = reason
        self.db.flush()
        if order.status not in ("cart",):
            self._freeze_bill(order)
        write_audit(self.db, actor=actor, action="order.void_item", entity="order_item",
                    entity_id=order_item_id, reason=reason, meta={"order_id": order_id})
        self.db.flush()
        publish_order_event("edited", order_id=order.id, status=order.status)
        return order

    def set_item_status(self, order_id: str, order_item_id: str, status: str) -> Order:
        if status not in ("pending", "ready", "served"):
            raise ValueError(f"Invalid item status '{status}'")
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        item = next((i for i in order.items if i.id == order_item_id), None)
        if not item:
            raise ValueError("Line item not found on this order")
        if item.status == "voided":
            raise ValueError("Can't change a voided item")
        item.status = status
        self.db.flush()
        publish_order_event("edited", order_id=order.id, status=order.status)
        return order

    def refund_order(self, order_id: str, reason: str, actor=None) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        if order.status != "paid":
            raise ValueError("Only a paid order can be refunded")
        if order.refunded:
            raise ValueError("Order is already refunded")
        order.refunded = True
        order.refund_reason = reason
        order.refunded_at = datetime.utcnow()
        self.db.flush()
        write_audit(self.db, actor=actor, action="order.refund", entity="order",
                    entity_id=order.id, reason=reason, meta={"total": float(order.total or 0)})
        self.db.flush()
        publish_order_event("refunded", order_id=order.id, status=order.status)
        return order

    def transfer_session(self, table_session_id: str, to_table_id: str, actor=None) -> None:
        """Move an open table session (all its orders) to a different table."""
        from db.repositories.table_repo import TableRepo
        from db.repositories.table_session_repo import TableSessionRepo
        ts_repo = TableSessionRepo(self.db)
        t_repo = TableRepo(self.db)
        sess = ts_repo.get_by_id(table_session_id)
        if not sess:
            raise ValueError("Table session not found")
        dest = t_repo.get_by_id(to_table_id)
        if not dest:
            raise ValueError("Destination table not found")
        if ts_repo.get_open_for_table(to_table_id):
            raise ValueError("Destination table already has an open tab")
        old_table_id = sess.table_id
        sess.table_id = to_table_id
        for o in self.order_repo.list_for_table_session(table_session_id):
            o.table_id = to_table_id
        t_repo.update(to_table_id, status="occupied")
        if old_table_id:
            t_repo.update(old_table_id, status="free")
        self.db.flush()
        write_audit(self.db, actor=actor, action="table.transfer", entity="table_session",
                    entity_id=table_session_id, meta={"from": old_table_id, "to": to_table_id})
        self.db.flush()
        publish_order_event("transfer", table_session_id=table_session_id)

    def merge_sessions(self, from_session_id: str, into_session_id: str, actor=None) -> None:
        """Merge one open tab into another (combine checks); close + free the source."""
        from db.repositories.table_repo import TableRepo
        from db.repositories.table_session_repo import TableSessionRepo
        ts_repo = TableSessionRepo(self.db)
        t_repo = TableRepo(self.db)
        src = ts_repo.get_by_id(from_session_id)
        dst = ts_repo.get_by_id(into_session_id)
        if not src or not dst:
            raise ValueError("Table session not found")
        if src.id == dst.id:
            raise ValueError("Can't merge a tab into itself")
        for o in self.order_repo.list_for_table_session(from_session_id):
            o.table_session_id = into_session_id
            o.table_id = dst.table_id
        src.status = "closed"
        src.closed_at = datetime.utcnow()
        if src.table_id:
            t_repo.update(src.table_id, status="free")
        self.db.flush()
        write_audit(self.db, actor=actor, action="table.merge", entity="table_session",
                    entity_id=into_session_id, meta={"from": from_session_id})
        self.db.flush()
        publish_order_event("merge", table_session_id=into_session_id)

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
