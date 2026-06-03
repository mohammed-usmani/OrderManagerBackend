"""Order and OrderItem models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


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
    )  # parcel (only type for now; kept extensible)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="cart"
    )  # cart | confirmed | awaiting_payment | paid | cancelled

    # Delivery snapshot, frozen onto the order at confirm time so it survives
    # later edits to the customer record.
    contact_name: Mapped[str | None] = mapped_column(String)
    contact_phone: Mapped[str | None] = mapped_column(String)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    delivery_area: Mapped[str | None] = mapped_column(String)
    delivery_pincode: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
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
