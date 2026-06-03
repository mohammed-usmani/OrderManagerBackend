"""ServiceArea model — the delivery "sphere of influence".

An admin-editable allowlist of localities/pincodes the kitchen delivers to.
The agent checks a customer's stated area or pincode against this list before
taking a parcel order, and politely declines anything outside it.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ServiceArea(Base):
    __tablename__ = "service_areas"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    pincode: Mapped[str | None] = mapped_column(String, index=True)
    # Spoken variants / nearby sub-localities customers might say
    # (e.g. ["pali hill", "pali naka", "carter road"]).
    aliases: Mapped[list | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
