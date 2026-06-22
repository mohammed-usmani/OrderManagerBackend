"""Payment model — records each settlement attempt (cash or Razorpay)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("orders.id"), nullable=True, index=True
    )
    table_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("table_sessions.id"), nullable=True, index=True
    )
    method: Mapped[str] = mapped_column(String, nullable=False)  # cash | upi | card | razorpay
    provider: Mapped[str | None] = mapped_column(String)  # "razorpay" | None
    provider_order_id: Mapped[str | None] = mapped_column(String, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # final charged
    tip_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, server_default="0", nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(
        String, default="created", nullable=False
    )  # created | paid | failed | refunded
    refund_amount: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
