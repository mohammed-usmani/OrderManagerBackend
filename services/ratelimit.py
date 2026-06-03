"""Per-IP voice-session limiting, backed by the same Redis as WS tickets.

Two cheap guards (a couple of Redis ops per call — negligible cost):
  - **one active call per IP** at a time (auto-expires if a session crashes),
  - **a cooldown** between calls so a single visitor can't hog the shared CPU.

Fails OPEN: if Redis is unreachable we allow the call rather than block real
users (and ticket minting already depends on Redis anyway).
"""

import redis as redis_lib
from loguru import logger

from config import MAX_SESSION_SECONDS, REDIS_URL, SESSION_COOLDOWN_SECONDS

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

_ACTIVE = "vc:active:{ip}"
_COOLDOWN = "vc:cooldown:{ip}"


def session_gate(ip: str) -> tuple[bool, str]:
    """Try to reserve a session slot for this IP.

    Returns (allowed, message). When not allowed, `message` is a friendly,
    human-readable reason suitable to show the visitor.
    """
    if not ip:
        return True, ""
    try:
        if SESSION_COOLDOWN_SECONDS > 0:
            ttl = _redis.ttl(_COOLDOWN.format(ip=ip))
            if ttl and ttl > 0:
                return False, (
                    f"You just finished a call — please wait about {ttl}s before "
                    "starting another. This is a demo, so we keep it fair for everyone."
                )
        # Atomic reserve — one active call per IP. Auto-expires if we crash.
        reserved = _redis.set(
            _ACTIVE.format(ip=ip), "1", nx=True, ex=MAX_SESSION_SECONDS + 30
        )
        if not reserved:
            return False, (
                "There's already a live call from your network. Please finish "
                "that one first — this demo allows one call at a time per visitor."
            )
        return True, ""
    except Exception as e:  # never block real users on a Redis hiccup
        logger.warning(f"rate-limit gate failed, allowing call: {e}")
        return True, ""


def session_release(ip: str) -> None:
    """Free the IP's active slot and start its cooldown."""
    if not ip:
        return
    try:
        _redis.delete(_ACTIVE.format(ip=ip))
        if SESSION_COOLDOWN_SECONDS > 0:
            _redis.setex(_COOLDOWN.format(ip=ip), SESSION_COOLDOWN_SECONDS, "1")
    except Exception as e:
        logger.warning(f"rate-limit release failed: {e}")
