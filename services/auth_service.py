"""Auth service: JWT creation/validation and Redis-backed WS tickets."""

import uuid
from datetime import datetime, timedelta, timezone

import redis as redis_lib
from jose import JWTError, jwt

from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET_KEY, REDIS_URL


class AuthService:
    def __init__(self, redis_client=None):
        if redis_client is None:
            self.redis = redis_lib.from_url(REDIS_URL, decode_responses=False)
        else:
            self.redis = redis_client

    def create_access_token(self, user_id: str, email: str, is_admin: bool) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
        payload = {
            "sub": user_id,
            "email": email,
            "is_admin": is_admin,
            "exp": expire,
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def decode_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}")

    def issue_ws_ticket(self, user_id: str) -> str:
        ticket = str(uuid.uuid4())
        self.redis.setex(f"ticket:{ticket}", 30, user_id.encode())
        return ticket

    def consume_ws_ticket(self, ticket: str) -> str | None:
        key = f"ticket:{ticket}"
        value = self.redis.get(key)
        if value is None:
            return None
        self.redis.delete(key)
        return value.decode() if isinstance(value, bytes) else value


# Module-level singleton for use outside FastAPI DI (e.g. dependencies.py)
auth_service = AuthService()
