"""AppSetting model — a tiny key/value store for admin-editable config.

Used for things that must change at runtime without a redeploy (the restaurant
runs on scale-to-zero Cloud Run, so there's no persistent local config). Today
it holds the bill ``charge_policy``; more keys can be added without a migration.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
