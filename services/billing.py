"""Context-aware bill computation.

The single source of truth for turning a subtotal into a bill. Charges depend on
the order context (dine-in vs parcel, and whether a dine-in table sits in an AC
zone), driven by ``config.CHARGE_POLICY``.

Backward compatible: ``compute_bill(subtotal)`` with no context behaves exactly
like the old parcel bill (service charge + GST), so existing callers keep working
unchanged.
"""

from decimal import Decimal

from config import CHARGE_POLICY
from services.money import money_float, to_money

# Admin-editable override (DB-backed, loaded by SettingsService at startup and on
# change). When None, the config default applies. Kept as a module cache so
# compute_bill stays a cheap pure-ish call — no DB hit per bill.
_policy_override: list[dict] | None = None


def set_policy_override(policy: list[dict] | None) -> None:
    """Install (or clear, with None) the active charge policy."""
    global _policy_override
    _policy_override = policy


def active_policy() -> list[dict]:
    """The charge policy currently in effect (override, else config default)."""
    return _policy_override if _policy_override is not None else CHARGE_POLICY


def compute_bill(
    subtotal: float,
    *,
    order_type: str = "parcel",
    is_ac: bool = False,
    policy: list[dict] | None = None,
) -> dict:
    """Apply the restaurant's charges on top of a subtotal, given context.

    Returns ``{subtotal, charges: [{label, rate, amount}], total}`` — the same
    shape the frontend already renders.
    """
    rules = policy if policy is not None else active_policy()
    sub = to_money(subtotal)
    charges: list[dict] = []
    running = sub
    for c in rules:
        applies_to = c.get("applies_to", "all")
        if applies_to != "all" and applies_to != order_type:
            continue
        if c.get("ac_only") and not is_ac:
            continue
        amount = to_money(sub * Decimal(str(c["rate"])))  # round each charge to paise
        charges.append({"label": c["label"], "rate": c["rate"], "amount": float(amount)})
        running += amount
    return {
        "subtotal": float(sub),
        "charges": charges,
        "total": money_float(running),
    }


def bill_for_order(order) -> dict:
    """Bill for an Order ORM row.

    Prefers the frozen snapshot (``charges_json`` + ``total``) captured at confirm
    time so historical bills never drift when the charge policy changes; falls
    back to a live computation from the order's context for carts/legacy rows.
    """
    items = list(order.items)
    subtotal = money_float(
        sum((to_money(i.price_at_order) * i.quantity for i in items), Decimal(0))
    )
    if order.charges_json is not None and order.total is not None:
        return {
            "subtotal": subtotal,
            "charges": list(order.charges_json),
            "total": float(order.total),
        }
    return compute_bill(
        subtotal,
        order_type=order.order_type or "parcel",
        is_ac=bool(order.is_ac),
    )
