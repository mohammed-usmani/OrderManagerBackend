"""Per-SESSION voice-call limiting, backed by the same Redis as WS tickets.

Keyed on a per-browser client id (the frontend generates one and stores it in
localStorage), NOT on IP — so different people behind one NAT never block each
other, while one browser still can't hold many concurrent calls.

Cheap (a couple of Redis ops per call). Messages are kept SHORT: they're sent as
the WebSocket close `reason`, capped at 123 bytes by the protocol. Fails OPEN on
any Redis error.
"""

import redis as redis_lib
from loguru import logger

from config import (
    MAX_CALLS_PER_SESSION,
    MAX_SESSION_SECONDS,
    REDIS_URL,
    SESSION_COOLDOWN_SECONDS,
)

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

_COUNT = "vc:s:count:{id}"
_COOLDOWN = "vc:s:cooldown:{id}"


def session_gate(session_id: str) -> tuple[bool, str]:
    """Reserve a call slot for this browser session. Returns (allowed, reason)."""
    if not session_id:
        return True, ""
    try:
        if SESSION_COOLDOWN_SECONDS > 0:
            ttl = _redis.ttl(_COOLDOWN.format(id=session_id))
            if ttl and ttl > 0:
                return False, f"Please wait ~{ttl}s before your next call (demo limit)."

        key = _COUNT.format(id=session_id)
        count = _redis.incr(key)
        # TTL so a crashed session can't leak the counter forever.
        _redis.expire(key, MAX_SESSION_SECONDS + 60)
        if count > MAX_CALLS_PER_SESSION:
            _redis.decr(key)
            return False, "You already have a call open. Finish that one first."
        return True, ""
    except Exception as e:  # never block real users on a Redis hiccup
        logger.warning(f"rate-limit gate failed, allowing call: {e}")
        return True, ""


def session_release(session_id: str) -> None:
    """Free this session's slot and (optionally) start its cooldown."""
    if not session_id:
        return
    try:
        key = _COUNT.format(id=session_id)
        if _redis.decr(key) < 0:
            _redis.set(key, 0)
        if SESSION_COOLDOWN_SECONDS > 0:
            _redis.setex(_COOLDOWN.format(id=session_id), SESSION_COOLDOWN_SECONDS, "1")
    except Exception as e:
        logger.warning(f"rate-limit release failed: {e}")
