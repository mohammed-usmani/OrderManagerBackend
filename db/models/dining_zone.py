"""DiningZone model — a room/section of the restaurant floor.

A zone groups tables (e.g. "AC Hall", "Garden", "Rooftop"). The ``is_ac`` flag
is what drives the AC surcharge on dine-in bills: orders seated in an AC zone
get a configurable AC charge added at confirm time. Zones are also the unit the
admin floor map is organised by.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class DiningZone(Base):
    __tablename__ = "dining_zones"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Drives the AC surcharge for dine-in orders seated in this zone.
    is_ac: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Ordering hint for the floor map / admin lists.
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    tables: Mapped[list["RestaurantTable"]] = relationship(  # noqa: F821
        "RestaurantTable", back_populates="zone"
    )
