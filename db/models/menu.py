"""MenuItem model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "M01"
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    how_its_made: Mapped[str | None] = mapped_column(Text)
    taste_profile: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String, default="INR", nullable=False)
    serving: Mapped[str | None] = mapped_column(String)
    dietary: Mapped[list | None] = mapped_column(JSONB)
    spice_level: Mapped[str | None] = mapped_column(String)
    popularity: Mapped[float | None] = mapped_column(Float)
    popularity_note: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
