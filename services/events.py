"""Order event bus over Redis pub/sub.

Order mutations publish a tiny event to the ``orders:events`` channel; the admin
KDS subscribes via SSE (`GET /admin/orders/stream`) and refetches on each event.
Redis pub/sub bridges Cloud Run's multiple instances. Publishing is best-effort
— a Redis hiccup must never break an order mutation.
"""

import json
from concurrent.futures import ThreadPoolExecutor

import redis as redis_lib

from config import REDIS_URL

CHANNEL = "orders:events"

_pub = None
# Publishing runs OFF the caller's thread/event loop. The order mutations that
# emit events live inside the async voice pipeline (sync DB tools on the loop);
# a blocking, cross-region Redis publish there would stall the loop and drop the
# Gemini Live socket. So we hand the publish to a tiny worker pool and return
# immediately — eventing is best-effort and must never slow a mutation.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="events-pub")


def _publisher():
    global _pub
    if _pub is None:
        _pub = redis_lib.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _pub


def _do_publish(payload: str) -> None:
    global _pub
    try:
        _publisher().publish(CHANNEL, payload)
    except Exception:
        _pub = None  # drop a broken connection so it's rebuilt next time


def publish_order_event(kind: str = "changed", **data) -> None:
    """Fire-and-forget notify that the order board changed (non-blocking)."""
    payload = json.dumps({"kind": kind, **data})
    try:
        _executor.submit(_do_publish, payload)
    except Exception:
        pass  # never let eventing break the mutation


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
