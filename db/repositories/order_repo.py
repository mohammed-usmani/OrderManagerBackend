"""Order and OrderItem repository."""

from sqlalchemy.orm import Session

from db.models.order import Order, OrderItem


class OrderRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, order_id: str) -> Order | None:
        return self.db.get(Order, order_id)

    def get_cart_for_user(self, user_id: str) -> Order | None:
        return (
            self.db.query(Order)
            .filter(Order.user_id == user_id, Order.status == "cart")
            .first()
        )

    def get_all_for_user(self, user_id: str) -> list[Order]:
        return (
            self.db.query(Order)
            .filter(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .all()
        )

    def get_cart_for_customer(self, customer_id: str) -> Order | None:
        return (
            self.db.query(Order)
            .filter(Order.customer_id == customer_id, Order.status == "cart")
            .first()
        )

    def get_cart_for_table(self, table_id: str) -> Order | None:
        """The current in-progress dine-in cart for a table (one at a time)."""
        return (
            self.db.query(Order)
            .filter(Order.table_id == table_id, Order.status == "cart")
            .first()
        )

    def get_all_for_customer(self, customer_id: str) -> list[Order]:
        return (
            self.db.query(Order)
            .filter(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc())
            .all()
        )

    def list_for_table_session(self, table_session_id: str) -> list[Order]:
        return (
            self.db.query(Order)
            .filter(Order.table_session_id == table_session_id)
            .order_by(Order.created_at)
            .all()
        )

    def list_all(self, statuses: list[str] | None = None) -> list[Order]:
        """Admin-scope: list every order, optionally filtered by status."""
        q = self.db.query(Order)
        if statuses:
            q = q.filter(Order.status.in_(statuses))
        return q.order_by(Order.created_at.desc()).all()

    def create(
        self, user_id: str | None = None, customer_id: str | None = None, **fields
    ) -> Order:
        """Create an order. ``fields`` may set dine-in columns (order_type,
        table_id, table_session_id, zone_name, is_ac)."""
        order = Order(user_id=user_id, customer_id=customer_id, **fields)
        self.db.add(order)
        self.db.flush()
        return order

    def get_item_in_order(self, order_id: str, menu_item_id: str) -> OrderItem | None:
        return (
            self.db.query(OrderItem)
            .filter(
                OrderItem.order_id == order_id,
                OrderItem.menu_item_id == menu_item_id,
            )
            .first()
        )

    def add_item(
        self,
        order_id: str,
        menu_item_id: str,
        quantity: int,
        price_at_order: float,
        special_instructions: str = "",
    ) -> OrderItem:
        existing = self.get_item_in_order(order_id, menu_item_id)
        if existing:
            existing.quantity += quantity
            self.db.flush()
            return existing
        item = OrderItem(
            order_id=order_id,
            menu_item_id=menu_item_id,
            quantity=quantity,
            price_at_order=price_at_order,
            special_instructions=special_instructions,
        )
        self.db.add(item)
        self.db.flush()
        return item

    def remove_item(self, order_id: str, menu_item_id: str) -> bool:
        item = self.get_item_in_order(order_id, menu_item_id)
        if not item:
            return False
        self.db.delete(item)
        self.db.flush()
        return True
