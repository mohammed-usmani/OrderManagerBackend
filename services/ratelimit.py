"""Per-IP voice-session limiting, backed by the same Redis as WS tickets.

Cheap guards (a couple of Redis ops per call):
  - up to MAX_CALLS_PER_IP simultaneous calls per public IP (several distinct
    people often share one IP, so this is >1 by default),
  - an optional cooldown between calls (off by default).

Messages are kept SHORT: they're sent as the WebSocket close `reason`, which is
capped at 123 bytes by the protocol. Fails OPEN on any Redis error.
"""

import redis as redis_lib
from loguru import logger

from config import (
    MAX_CALLS_PER_IP,
    MAX_SESSION_SECONDS,
    REDIS_URL,
    SESSION_COOLDOWN_SECONDS,
)

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

_COUNT = "vc:count:{ip}"
_COOLDOWN = "vc:cooldown:{ip}"


def session_gate(ip: str) -> tuple[bool, str]:
    """Reserve a call slot for this IP. Returns (allowed, short_reason)."""
    if not ip:
        return True, ""
    try:
        if SESSION_COOLDOWN_SECONDS > 0:
            ttl = _redis.ttl(_COOLDOWN.format(ip=ip))
            if ttl and ttl > 0:
                return False, f"Please wait ~{ttl}s before the next call (demo limit)."

        key = _COUNT.format(ip=ip)
        count = _redis.incr(key)
        # TTL so a crashed session can't leak the counter forever.
        _redis.expire(key, MAX_SESSION_SECONDS + 60)
        if count > MAX_CALLS_PER_IP:
            _redis.decr(key)
            return False, f"Network is at the {MAX_CALLS_PER_IP}-call demo limit. Try again shortly."
        return True, ""
    except Exception as e:  # never block real users on a Redis hiccup
        logger.warning(f"rate-limit gate failed, allowing call: {e}")
        return True, ""


def session_release(ip: str) -> None:
    """Free this IP's slot and (optionally) start its cooldown."""
    if not ip:
        return
    try:
        key = _COUNT.format(ip=ip)
        if _redis.decr(key) < 0:
            _redis.set(key, 0)
        if SESSION_COOLDOWN_SECONDS > 0:
            _redis.setex(_COOLDOWN.format(ip=ip), SESSION_COOLDOWN_SECONDS, "1")
    except Exception as e:
        logger.warning(f"rate-limit release failed: {e}")
