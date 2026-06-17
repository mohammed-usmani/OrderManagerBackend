"""Exact money arithmetic.

Money must never be computed with binary floats (0.1 + 0.2 != 0.3) — drift
accumulates across charges and orders. All bill math goes through Decimal here,
rounded to paise (2 dp, banker-safe HALF_UP), and only converted to float at the
serialization boundary (the API/JSON contract is float).
"""

from decimal import Decimal, ROUND_HALF_UP

_CENTS = Decimal("0.01")


def to_money(value) -> Decimal:
    """Coerce any number to a Decimal rounded to 2 dp (paise)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def money_float(value) -> float:
    """2-dp value as a float, for the API/JSON layer."""
    return float(to_money(value))
