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
    user = UserRepo(db).get_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(current_user=Depends(get_current_user)):
    """Require the current user to be an admin. Raises 403 otherwise."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
