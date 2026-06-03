"""Order service: cart lifecycle and item management."""

from datetime import datetime

from sqlalchemy.orm import Session

from db.models.order import Order
from db.repositories.chat_repo import ChatRepo
from db.repositories.menu_repo import MenuRepo
from db.repositories.order_repo import OrderRepo


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
        cart = self.order_repo.create(customer_id=customer_id)
        self.chat_repo.create_session(order_id=cart.id, customer_id=customer_id)
        return cart

    def add_item(
        self,
        order_id: str,
        menu_item_id: str,
        quantity: int = 1,
        special_instructions: str = "",
    ):
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
        if not self.order_repo.remove_item(order_id, menu_item_id):
            raise ValueError(f"Item '{menu_item_id}' not found in order")

    def set_item_quantity(
        self, order_id: str, menu_item_id: str, quantity: int
    ):
        """Set the ABSOLUTE quantity of an item (not a delta).

        quantity <= 0 removes the line. If the item isn't in the order yet it's
        added at the requested quantity.
        """
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

    def confirm_order(self, order_id: str, customer=None) -> Order:
        order = self.order_repo.get_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        if order.status != "cart":
            raise ValueError(f"Cannot confirm order with status '{order.status}'")
        if not order.items:
            raise ValueError("Cannot confirm an empty order")
        order.status = "confirmed"
        order.confirmed_at = datetime.utcnow()

        # Freeze the delivery snapshot onto the order so it survives later edits
        # to the customer record, and bump the customer's order stats.
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
        session = self.chat_repo.get_session_for_order(order_id)
        if session:
            session.status = "closed"
            session.closed_at = datetime.utcnow()
            self.db.flush()
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
