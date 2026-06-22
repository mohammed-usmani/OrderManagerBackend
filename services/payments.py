"""Razorpay (TEST mode) helpers — order creation + signature/webhook verify.

Pure provider glue; no DB. When keys are unset, ``razorpay_enabled()`` is False
and the app offers cash-only settlement.
"""

import hashlib
import hmac

from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET


def razorpay_enabled() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def create_razorpay_order(amount_rupees: float, receipt: str) -> dict:
    """Create a Razorpay order. Amount is converted to paise (int)."""
    import razorpay

    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    amount_paise = int(round(amount_rupees * 100))
    return client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt[:40],
            "payment_capture": 1,
        }
    )


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify the checkout callback signature: HMAC_SHA256(order_id|payment_id)."""
    if not RAZORPAY_KEY_SECRET:
        return False
    msg = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    if not RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")
