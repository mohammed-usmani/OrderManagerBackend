"""UI event pushing for the voice pipeline.

Tools push structured payloads over the WebSocket so the frontend can render
cards (menu results, cart, order history, confirmation). Uses Pipecat's
OutputTransportMessageUrgentFrame which the protobuf serializer wraps in a
MessageFrame(data=json).
"""

import json
from typing import Any

from pipecat.frames.frames import OutputTransportMessageUrgentFrame
from pipecat.services.llm_service import LLMService

# Canonical billing lives in services.billing; re-exported here so existing
# callers (`from pipeline.ui_events import compute_bill`) keep working.
from services.billing import bill_for_order, compute_bill  # noqa: F401


async def push_ui_event(llm: LLMService, event_type: str, payload: Any) -> None:
    """Send a UI event to the connected client.

    The client receives a MessageFrame whose `data` is this JSON:
        { "kind": "ui_event", "event": <event_type>, "data": <payload> }
    """
    message = {
        "kind": "ui_event",
        "event": event_type,
        "data": payload,
    }
    frame = OutputTransportMessageUrgentFrame(message=message)
    # LLMService.push_frame sends downstream toward the transport.
    await llm.push_frame(frame)


def menu_item_to_card(item) -> dict:
    """MenuItem ORM → UI card dict."""
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "taste_profile": item.taste_profile,
        "how_its_made": item.how_its_made,
        "category": item.category,
        "price": float(item.price),
        "currency": item.currency,
        "serving": item.serving,
        "dietary": list(item.dietary) if item.dietary else [],
        "spice_level": item.spice_level,
        "popularity": item.popularity,
        "image_url": item.image_url,
        "available": bool(item.available),
    }


def customer_to_card(customer) -> dict:
    """Customer ORM → UI card dict (shown when the agent identifies a caller)."""
    return {
        "id": customer.id,
        "code": customer.code,
        "name": customer.name,
        "phone": customer.phone,
        "address_line": customer.address_line,
        "area": customer.area,
        "pincode": customer.pincode,
        "landmark": customer.landmark,
        "preferences": customer.preferences,
        "allergies": customer.allergies,
        "order_count": customer.order_count,
    }


def order_item_to_card(item, menu_repo) -> dict:
    """OrderItem ORM → UI line item."""
    menu_item = menu_repo.get_by_id(item.menu_item_id)
    return {
        "id": item.id,
        "menu_item_id": item.menu_item_id,
        "name": menu_item.name if menu_item else item.menu_item_id,
        "category": menu_item.category if menu_item else None,
        "quantity": item.quantity,
        "price_at_order": float(item.price_at_order),
        "line_total": float(item.price_at_order) * item.quantity,
        "special_instructions": item.special_instructions,
    }


def order_to_card(order, menu_repo) -> dict:
    """Order ORM → UI card dict with full bill breakdown.

    Bill is context-aware (dine-in/parcel, AC zone) and prefers the frozen
    snapshot on confirmed orders. Dine-in fields are included so the frontend can
    render a table header / running tab; the parcel UI simply ignores them.
    """
    items = [order_item_to_card(i, menu_repo) for i in order.items]
    bill = bill_for_order(order)

    def _iso(dt):
        return dt.isoformat() if dt else None

    return {
        "id": order.id,
        "status": order.status,
        "order_type": order.order_type,
        # Dine-in context (None for parcel orders).
        "table_id": order.table_id,
        "table_session_id": order.table_session_id,
        "zone_name": order.zone_name,
        "is_ac": order.is_ac,
        "created_at": _iso(order.created_at),
        "confirmed_at": _iso(order.confirmed_at),
        "served_at": _iso(order.served_at),
        "ready_at": _iso(order.ready_at),
        "delivered_at": _iso(order.delivered_at),
        "paid_at": _iso(order.paid_at),
        "items": items,
        "item_count": sum(i["quantity"] for i in items),
        "subtotal": bill["subtotal"],
        "charges": bill["charges"],
        "total": bill["total"],
    }
