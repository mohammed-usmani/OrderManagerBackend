"""Per-connection call state for the voice line (parcel **and** dine-in).

Parcel calls are anonymous until the agent identifies the caller mid-chat
(lookup/register_customer). Dine-in calls instead arrive already bound to a
table (the guest scanned its QR), so the session is "seated" up front and the
cart/order tools build the table's running tab — no customer identification or
delivery needed. The tool wrappers share one mutable CallSession.
"""

from dataclasses import dataclass


@dataclass
class CallSession:
    # Mode: "parcel" (default) or "dine_in".
    order_type: str = "parcel"

    # --- Parcel: set once the agent identifies/registers the caller ---
    customer_id: str | None = None
    customer_code: str | None = None
    customer_name: str | None = None

    # --- Dine-in: set when the call is bound to a table (QR or voice fallback) ---
    table_id: str | None = None
    table_label: str | None = None
    table_session_id: str | None = None
    zone_name: str | None = None
    is_ac: bool = False

    def identify(self, customer) -> None:
        self.customer_id = customer.id
        self.customer_code = customer.code
        self.customer_name = customer.name

    def seat(self, *, table_id, table_label, zone_name, is_ac) -> None:
        """Bind this (dine-in) call to a table."""
        self.order_type = "dine_in"
        self.table_id = table_id
        self.table_label = table_label
        self.zone_name = zone_name
        self.is_ac = bool(is_ac)

    @property
    def is_identified(self) -> bool:
        return self.customer_id is not None

    @property
    def is_seated(self) -> bool:
        return self.table_id is not None

    @property
    def can_order(self) -> bool:
        """Whether cart/order tools may operate yet."""
        if self.order_type == "dine_in":
            return self.is_seated
        return self.is_identified
