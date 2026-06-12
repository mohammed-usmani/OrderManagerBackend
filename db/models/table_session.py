"""TableSession model — one dining visit / running tab for a table.

A party seated at a table may order several "rounds" over their visit (each a
separate :class:`Order`). They're grouped under one open ``TableSession`` so the
floor map shows a single live tab and the table is settled with one combined
check. Lifecycle: ``open`` → ``billed`` (customer asked for the bill) → ``closed``
(paid, table freed).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class TableSession(Base):
    __tablename__ = "table_sessions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    table_id: Mapped[str] = mapped_column(
        String, ForeignKey("restaurant_tables.id"), nullable=False, index=True
    )
    # open | billed | closed
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    party_size: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    opened_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    table: Mapped["RestaurantTable"] = relationship("RestaurantTable")  # noqa: F821
