"""Shared FastAPI dependencies for auth and DB."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import AUTH_COOKIE_NAME
from db.base import get_db
from db.repositories.user_repo import UserRepo
from services.auth_service import auth_service
from services.ratelimit import allow

_bearer = HTTPBearer(auto_error=False)


def request_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """The caller's JWT: the Authorization header (scripts, tests) or else the
    browser's httpOnly session cookie."""
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(AUTH_COOKIE_NAME)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db=Depends(get_db),
):
    """Decode the caller's JWT and return the current User. Raises 401 if invalid."""
    token = request_token(request, credentials)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    try:
        payload = auth_service.decode_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    user = UserRepo(db).get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db=Depends(get_db),
):
    """The signed-in user if a valid token was sent, otherwise None (never 401s)."""
    try:
        return get_current_user(request, credentials, db)
    except HTTPException:
        return None


def rate_limit(bucket: str, limit: int, window_s: int):
    """Dependency: 429 once a client IP exceeds ``limit`` requests per window."""
    def _dep(request: Request):
        ip = request.client.host if request.client else "unknown"
        if not allow(bucket, ip, limit, window_s):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait a moment and try again.",
            )
    return _dep


def require_admin(current_user=Depends(get_current_user)):
    """Require the current user to be an admin (owner/manager). 403 otherwise."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_roles(allowed: set[str]):
    """Build a dependency that requires the user's role to be in ``allowed``."""
    def _dep(current_user=Depends(get_current_user)):
        if getattr(current_user, "role", None) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this action",
            )
        return current_user
    return _dep

