"""Floor model — a physical storey/level of the restaurant.

The top of the spatial hierarchy: Floor → DiningZone → RestaurantTable. A floor
(e.g. "Ground Floor", "Rooftop") holds zones (AC Hall, Garden, Bar) which in
turn hold tables. ``width``/``height`` define the floor-plan canvas's logical
coordinate space; table ``pos_x``/``pos_y`` are points within it.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Floor(Base):
    __tablename__ = "floors"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Floor-plan canvas logical size (table coords live in this space).
    width: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=640, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    zones: Mapped[list["DiningZone"]] = relationship(  # noqa: F821
        "DiningZone", back_populates="floor"
    )
