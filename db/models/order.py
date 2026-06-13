"""Order and OrderItem models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

# Ensure the FK-target tables below (restaurant_tables, table_sessions, and the
# dining_zones they reference) are registered with the mapper registry whenever
# Order is loaded — Order is imported everywhere it's used, so this guarantees
# its foreign keys always resolve. These modules only depend on Base (no cycle).
import db.models.floor  # noqa: F401, E402
import db.models.dining_zone  # noqa: F401, E402
import db.models.restaurant_table  # noqa: F401, E402
import db.models.table_session  # noqa: F401, E402


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Legacy link to authenticated users — nullable now that the voice line is
    # public. Parcel orders use customer_id instead.
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("customers.id"), nullable=True, index=True
    )
    order_type: Mapped[str] = mapped_column(
        String, nullable=False, default="parcel"
    )  # parcel | dine_in
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="cart"
    )  # cart | placed | cooking | served (dine_in) | ready | delivered (parcel)
    # | paid | cancelled  (legacy rows may still hold confirmed/awaiting_payment)

    # Delivery snapshot (parcel) — frozen onto the order at confirm time so it
    # survives later edits to the customer record.
    contact_name: Mapped[str | None] = mapped_column(String)
    contact_phone: Mapped[str | None] = mapped_column(String)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    delivery_area: Mapped[str | None] = mapped_column(String)
    delivery_pincode: Mapped[str | None] = mapped_column(String)

    # Dine-in linkage + zone snapshot (frozen at confirm for stable history).
    table_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("restaurant_tables.id"), nullable=True, index=True
    )
    table_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("table_sessions.id"), nullable=True, index=True
    )
    zone_name: Mapped[str | None] = mapped_column(String)
    floor_name: Mapped[str | None] = mapped_column(String)
    is_ac: Mapped[bool | None] = mapped_column(Boolean)

    # Bill snapshot, frozen at confirm so historical totals don't drift when the
    # charge configuration changes. ``charges_json`` mirrors compute_bill()'s
    # ``charges`` list; ``total`` is subtotal + all charges.
    charges_json: Mapped[list | None] = mapped_column(JSONB)
    total: Mapped[float | None] = mapped_column(Numeric(10, 2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Lifecycle timestamps. served_at (dine-in); ready_at/delivered_at (parcel).
    served_at: Mapped[datetime | None] = mapped_column(DateTime)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        String, ForeignKey("orders.id"), nullable=False, index=True
    )
    menu_item_id: Mapped[str] = mapped_column(
        String, ForeignKey("menu_items.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_at_order: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    special_instructions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    order: Mapped["Order"] = relationship("Order", back_populates="items")
