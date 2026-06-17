"""Auth service: JWT creation/validation and Redis-backed WS tickets."""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import redis as redis_lib
from jose import JWTError, jwt

from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET_KEY, REDIS_URL

# Login brute-force protection.
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 900  # 15 min


class AuthService:
    def __init__(self, redis_client=None):
        if redis_client is None:
            self.redis = redis_lib.from_url(REDIS_URL, decode_responses=False)
        else:
            self.redis = redis_client

    def create_access_token(self, user_id: str, email: str, is_admin: bool) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "email": email,
            "is_admin": is_admin,
            "iat": now,
            "jti": uuid.uuid4().hex,  # unique id → enables revocation
            "exp": now + timedelta(days=JWT_EXPIRE_DAYS),
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def decode_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}")
        jti = payload.get("jti")
        if jti:
            try:
                revoked = self.redis.get(f"revoked:{jti}")
            except Exception:
                revoked = None  # Redis down — fail open (don't lock everyone out)
            if revoked:
                raise ValueError("Token has been revoked")
        return payload

    def revoke_token(self, token: str) -> None:
        """Deny-list a token's jti until it would naturally expire (logout)."""
        try:
            payload = jwt.decode(
                token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM],
                options={"verify_exp": False},
            )
        except JWTError:
            return
        jti, exp = payload.get("jti"), payload.get("exp")
        if not jti:
            return
        ttl = int(exp - time.time()) if exp else 3600
        if ttl <= 0:
            return
        try:
            self.redis.setex(f"revoked:{jti}", ttl, b"1")
        except Exception:
            pass

    # --- login brute-force lockout (fail-open if Redis is unavailable) ---

    def _login_key(self, email: str) -> str:
        return f"login_fail:{(email or '').strip().lower()}"

    def login_locked(self, email: str) -> bool:
        try:
            return int(self.redis.get(self._login_key(email)) or 0) >= LOGIN_MAX_FAILS
        except Exception:
            return False

    def record_login_failure(self, email: str) -> None:
        try:
            key = self._login_key(email)
            if self.redis.incr(key) == 1:
                self.redis.expire(key, LOGIN_LOCK_SECONDS)
        except Exception:
            pass

    def clear_login_failures(self, email: str) -> None:
        try:
            self.redis.delete(self._login_key(email))
        except Exception:
            pass

    def issue_ws_ticket(
        self,
        user_id: str | None = None,
        timezone: str | None = None,
        table_token: str | None = None,
    ) -> str:
        """Issue a single-use WS ticket carrying optional timezone + table token.

        The voice line is public, so ``user_id`` is optional (anonymous parcel
        callers). ``table_token`` binds a dine-in call to a table (the guest
        scanned its QR). Payload is JSON so we can extend it without breaking
        tickets.
        """
        ticket = str(uuid.uuid4())
        payload = json.dumps(
            {"user_id": user_id, "timezone": timezone, "table_token": table_token}
        )
        self.redis.setex(f"ticket:{ticket}", 30, payload.encode())
        return ticket

    def consume_ws_ticket(self, ticket: str) -> dict | None:
        """Consume a WS ticket, returning {user_id, timezone, table_token} or None.

        Returns None only when the ticket is missing/expired — a valid
        anonymous ticket returns {"user_id": None, "timezone": ..., "table_token": ...}.
        """
        key = f"ticket:{ticket}"
        # Atomic get-and-delete so a ticket can be redeemed exactly once (a
        # plain get + delete lets two concurrent connects both pass).
        value = self.redis.getdel(key)
        if value is None:
            return None
        raw = value.decode() if isinstance(value, bytes) else value
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {
                    "user_id": data.get("user_id"),
                    "timezone": data.get("timezone"),
                    "table_token": data.get("table_token"),
                }
        except (ValueError, TypeError):
            pass
        # Back-compat: old tickets stored the raw user_id string.
        return {"user_id": raw, "timezone": None, "table_token": None}


# Module-level singleton for use outside FastAPI DI (e.g. dependencies.py)
auth_service = AuthService()
