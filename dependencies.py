"""Shared FastAPI dependencies for auth and DB."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db.base import get_db
from db.repositories.user_repo import UserRepo
from services.auth_service import auth_service

_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db=Depends(get_db),
):
    """Decode JWT and return the current User. Raises 401 if invalid."""
    try:
        payload = auth_service.decode_token(credentials.credentials)
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
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db=Depends(get_db),
):
    """The signed-in user if a valid token was sent, otherwise None (never 401s)."""
    if credentials is None:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


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

