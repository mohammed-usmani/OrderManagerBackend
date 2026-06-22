"""AuditLog model — who did what (voids, comps, refunds, settles, transfers)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    actor_user_id: Mapped[str | None] = mapped_column(String, index=True)
    actor_email: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String, nullable=False)  # e.g. order.void_item
    entity: Mapped[str] = mapped_column(String, nullable=False)  # order | order_item | table_session
    entity_id: Mapped[str | None] = mapped_column(String, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
