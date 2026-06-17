"""Auth router: register, login, ws-ticket."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import get_current_user
from services.auth_service import auth_service
from services.user_service import UserService, validate_registration

_bearer = HTTPBearer()

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TicketRequest(BaseModel):
    timezone: str | None = None
    table_token: str | None = None  # binds a dine-in call to a table (QR scan)


class TicketResponse(BaseModel):
    ticket: str


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        validate_registration(req.email, req.password, req.name)
        user = UserService(db).register(req.email.strip().lower(), req.password, req.name.strip())
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    token = auth_service.create_access_token(user.id, user.email, user.is_admin)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    if auth_service.login_locked(req.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please try again in a few minutes.",
        )
    try:
        user = UserService(db).login(req.email, req.password)
    except ValueError:
        auth_service.record_login_failure(req.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    auth_service.clear_login_failures(req.email)
    token = auth_service.create_access_token(user.id, user.email, user.is_admin)
    return TokenResponse(access_token=token)


@router.post("/logout")
def logout(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    _user=Depends(get_current_user),
):
    """Revoke the caller's token (deny-listed until it would expire)."""
    auth_service.revoke_token(creds.credentials)
    return {"ok": True}


@router.post("/ws-ticket", response_model=TicketResponse)
def ws_ticket(req: TicketRequest | None = None):
    """Public — the voice line is open to anyone (anonymous parcel callers).

    Issues a short-lived, single-use ticket carrying only the caller's
    timezone. The caller is identified later, in-conversation, by the agent.
    """
    timezone = req.timezone if req else None
    table_token = req.table_token if req else None
    ticket = auth_service.issue_ws_ticket(timezone=timezone, table_token=table_token)
    return TicketResponse(ticket=ticket)
