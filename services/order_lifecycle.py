"""Order lifecycle state machine.

Centralises the allowed status transitions so every caller (admin KDS, voice
tools, REST) validates the same way. Two flows share the pre-fulfilment states
(``cart`` → ``confirmed``) then diverge:

    dine_in:  cart → confirmed → cooking → served → paid
    parcel:   cart → confirmed → cooking → ready → delivered → paid
    (either may go → cancelled from any pre-paid, non-cart-or-later state)

``confirmed`` is the existing post-cart status (kept, not renamed), so adopting
this engine needs no data migration. ``awaiting_payment`` is a legacy state that
older parcel rows may still hold; it's allowed to settle straight to ``paid``.
"""

# --- Order types (single source of truth; plain strings to match the
# String columns and avoid str-Enum DB-binding footguns) ---
PARCEL = "parcel"
DINE_IN = "dine_in"


class OrderType:
    PARCEL = PARCEL
    DINE_IN = DINE_IN


# --- Order statuses ---
CART = "cart"
CONFIRMED = "confirmed"
COOKING = "cooking"
SERVED = "served"
READY = "ready"
DELIVERED = "delivered"
PAID = "paid"
CANCELLED = "cancelled"
# Legacy (pre-lifecycle) parcel state — bridged so it can still be settled.
AWAITING_PAYMENT = "awaiting_payment"

_DINE_IN_FLOW: dict[str, set[str]] = {
    CART: {CONFIRMED, CANCELLED},
    CONFIRMED: {COOKING, CANCELLED},
    COOKING: {SERVED, CANCELLED},
    SERVED: {PAID},
    PAID: set(),
    CANCELLED: set(),
}

_PARCEL_FLOW: dict[str, set[str]] = {
    CART: {CONFIRMED, CANCELLED},
    CONFIRMED: {COOKING, CANCELLED},
    COOKING: {READY, CANCELLED},
    READY: {DELIVERED, CANCELLED},
    DELIVERED: {PAID},
    PAID: set(),
    CANCELLED: set(),
    # Legacy bridge: old confirmed→awaiting_payment→paid rows can still be paid.
    AWAITING_PAYMENT: {PAID, CANCELLED},
}


def _flow(order_type: str) -> dict[str, set[str]]:
    return _DINE_IN_FLOW if order_type == DINE_IN else _PARCEL_FLOW


def allowed_next(order_type: str, status: str) -> set[str]:
    """The statuses an order may legally move to from its current status."""
    return _flow(order_type).get(status, set())


def can_transition(order_type: str, from_status: str, to_status: str) -> bool:
    return to_status in allowed_next(order_type, from_status)


def assert_transition(order_type: str, from_status: str, to_status: str) -> None:
    """Raise ValueError if the transition is not allowed for this order type."""
    if not can_transition(order_type, from_status, to_status):
        raise ValueError(
            f"Cannot move a {order_type} order from '{from_status}' to "
            f"'{to_status}'"
        )


# Status → the timestamp column stamped when an order ENTERS that status.
STATUS_TIMESTAMP: dict[str, str] = {
    CONFIRMED: "confirmed_at",
    SERVED: "served_at",
    READY: "ready_at",
    DELIVERED: "delivered_at",
    PAID: "paid_at",
}

# Statuses that still need kitchen/fulfilment work (drive the KDS board).
OPEN_STATUSES: set[str] = {CONFIRMED, COOKING, SERVED, READY, DELIVERED, AWAITING_PAYMENT}
# Terminal statuses.
CLOSED_STATUSES: set[str] = {PAID, CANCELLED}
