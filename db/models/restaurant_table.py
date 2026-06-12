"""RestaurantTable model — a single table on the floor.

Each table belongs to a :class:`DiningZone` and carries an unguessable
``qr_token``. The token is encoded in the table's printed QR tent card; scanning
it opens the ordering app already bound to this table, which is how the voice
agent knows where a dine-in customer is sitting without any staff help (and even
when the customer doesn't know their table number).

``status`` reflects floor state for the admin map; the authoritative "is there
an open tab" lives on :class:`TableSession`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _qr_token() -> str:
    """Short, unguessable token for a table's QR tent card."""
    return uuid.uuid4().hex


class RestaurantTable(Base):
    __tablename__ = "restaurant_tables"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    zone_id: Mapped[str] = mapped_column(
        String, ForeignKey("dining_zones.id"), nullable=False, index=True
    )
    # Human label the customer / staff use (e.g. "7", "T7", "Patio 2").
    label: Mapped[str] = mapped_column(String, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # Floor-map coordinates (admin drag-to-place layout). Nullable until placed.
    pos_x: Mapped[int | None] = mapped_column(Integer)
    pos_y: Mapped[int | None] = mapped_column(Integer)

    # Encoded in the QR tent card → /t/<qr_token>. Unique + indexed for lookup.
    qr_token: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=_qr_token
    )
    # free | occupied | needs_bill | cleaning
    status: Mapped[str] = mapped_column(String, default="free", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    zone: Mapped["DiningZone"] = relationship(  # noqa: F821
        "DiningZone", back_populates="tables"
    )
