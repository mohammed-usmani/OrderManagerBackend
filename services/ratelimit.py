"""Global concurrency cap for voice calls, backed by the same Redis as tickets.

The real limit is the Gemini free tier (~3 concurrent Live sessions), which is a
*global* cap, not per-user. We track active calls in a Redis sorted set keyed by
a per-call id with the start timestamp as score, so:

  - we count concurrency across ALL Cloud Run instances (shared Redis),
  - stale entries (a crashed/killed session that never released) are pruned by
    age, so the cap can never get permanently stuck,
  - a returning user gets a slot the instant one is free — no per-user block.

Callers that don't get a slot are told "busy"; the frontend auto-retries (queue).
Fails OPEN on any Redis error.
"""

import time

import redis as redis_lib
from loguru import logger

from config import MAX_CONCURRENT_CALLS, MAX_SESSION_SECONDS, REDIS_URL

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

_ACTIVE = "vc:concurrent"
# An entry older than this is assumed dead (a call can't outlive the time cap).
_STALE_AFTER = MAX_SESSION_SECONDS + 60


def allow(bucket: str, key: str, limit: int, window_s: int) -> bool:
    """Fixed-window rate limit: at most ``limit`` hits per ``window_s`` for
    ``key`` in ``bucket``. Fails open on Redis errors (logged)."""
    counter = f"rl:{bucket}:{key}:{int(time.time() // window_s)}"
    try:
        hits = _redis.incr(counter)
        if hits == 1:
            _redis.expire(counter, window_s)
        return hits <= limit
    except Exception as e:
        logger.warning(f"rate limit check failed, allowing: {e}")
        return True


def acquire_slot(call_id: str) -> tuple[bool, str]:
    """Try to take one of the global concurrency slots. (allowed, reason)."""
    try:
        now = time.time()
        # Drop any leaked entries from crashed sessions first.
        _redis.zremrangebyscore(_ACTIVE, 0, now - _STALE_AFTER)
        _redis.zadd(_ACTIVE, {call_id: now})
        if _redis.zcard(_ACTIVE) > MAX_CONCURRENT_CALLS:
            _redis.zrem(_ACTIVE, call_id)  # give the slot back
            return False, "All voice lines are busy right now."
        return True, ""
    except Exception as e:  # never block real users on a Redis hiccup
        logger.warning(f"concurrency acquire failed, allowing call: {e}")
        return True, ""


def release_slot(call_id: str) -> None:
    """Release a concurrency slot when the call ends."""
    try:
        _redis.zrem(_ACTIVE, call_id)
    except Exception as e:
        logger.warning(f"concurrency release failed: {e}")
