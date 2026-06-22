"""Order event bus over Redis pub/sub.

Order mutations publish a tiny event to the ``orders:events`` channel; the admin
KDS subscribes via SSE (`GET /admin/orders/stream`) and refetches on each event.
Redis pub/sub bridges Cloud Run's multiple instances. Publishing is best-effort
— a Redis hiccup must never break an order mutation.
"""

import json

import redis as redis_lib

from config import REDIS_URL

CHANNEL = "orders:events"

_pub = None


def _publisher():
    global _pub
    if _pub is None:
        _pub = redis_lib.from_url(REDIS_URL, decode_responses=True)
    return _pub


def publish_order_event(kind: str = "changed", **data) -> None:
    """Fire-and-forget notify that the order board changed."""
    try:
        _publisher().publish(CHANNEL, json.dumps({"kind": kind, **data}))
    except Exception:
        pass  # eventing is a nicety; never let it break the mutation


async def subscribe_order_events():
    """Async generator yielding raw event payloads from the channel (for SSE)."""
    import redis.asyncio as aredis

    client = aredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                yield msg["data"]
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()
            await client.aclose()
        except Exception:
            pass
