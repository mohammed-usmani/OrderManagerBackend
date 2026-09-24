"""Customer model.

Parcel callers are NOT authenticated users — they're identified during the
voice call by a short 4-digit ``code`` (read back digit-by-digit) or, as a
secondary lookup, their phone number. This table is fully decoupled from
``users`` (which now exists only to gate the admin panel).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Customer(Base):
    __tablename__ = "customers"
    # Matches the schema the migrations create: unique constraints + plain indexes.
    __table_args__ = (
        UniqueConstraint("code", name="customers_code_key"),
        UniqueConstraint("phone", name="customers_phone_key"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # The memorable identifier the customer quotes on return (e.g. "4821").
    code: Mapped[str] = mapped_column(String, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String)

    # Delivery details.
    address_line: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(String)
    pincode: Mapped[str | None] = mapped_column(String)
    landmark: Mapped[str | None] = mapped_column(String)

    # Free-text context the agent uses to personalise the conversation.
    preferences: Mapped[str | None] = mapped_column(Text)
    allergies: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
