"""Auth router: register, login, logout, me, ws-ticket.

Browsers authenticate with an httpOnly session cookie set here, so page scripts
never see the JWT. The same token is still accepted as a Bearer header for
scripts and tests (see dependencies.get_current_user).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import AUTH_COOKIE_NAME, AUTH_COOKIE_SECURE, JWT_EXPIRE_DAYS
from db.base import get_db
from dependencies import _bearer, get_current_user, rate_limit, request_token
from services.auth_service import auth_service
from services.user_service import UserService, validate_registration

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None = None
    role: str
    is_admin: bool


class SessionResponse(BaseModel):
    user: UserOut


class TicketRequest(BaseModel):
    timezone: str | None = None
    table_token: str | None = None  # binds a dine-in call to a table (QR scan)


class TicketResponse(BaseModel):
    ticket: str


def _session(response: Response, user) -> SessionResponse:
    """Sign the user in: set the session cookie and return who they are."""
    token = auth_service.create_access_token(user.id, user.email, user.is_admin, user.role)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=JWT_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return SessionResponse(user=UserOut.model_validate(user, from_attributes=True))


@router.post(
    "/register",
    response_model=SessionResponse,
    dependencies=[Depends(rate_limit("register", limit=5, window_s=3600))],
)
def register(req: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    try:
        validate_registration(req.email, req.password, req.name)
        # Public sign-up never grants staff access — staff are provisioned by an
        # owner/manager via the staff endpoints with an explicit role.
        user = UserService(db).register(req.email.strip().lower(), req.password, req.name.strip())
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _session(response, user)


@router.post(
    "/login",
    response_model=SessionResponse,
    dependencies=[Depends(rate_limit("login", limit=10, window_s=60))],
)
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
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
    return _session(response, user)


@router.get("/me", response_model=SessionResponse)
def me(user=Depends(get_current_user)):
    return SessionResponse(user=UserOut.model_validate(user, from_attributes=True))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Revoke the caller's token (deny-listed until it would expire) and clear
    the cookie. Always succeeds, so a stale session can still sign out."""
    token = request_token(request, credentials)
    if token:
        auth_service.revoke_token(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        AUTH_COOKIE_NAME, path="/", httponly=True, secure=AUTH_COOKIE_SECURE, samesite="lax"
    )
    return response


@router.post(
    "/ws-ticket",
    response_model=TicketResponse,
    dependencies=[Depends(rate_limit("ws_ticket", limit=20, window_s=60))],
)
def ws_ticket(req: TicketRequest | None = None):
    """Public — the voice line is open to anyone (anonymous parcel callers).

    Issues a short-lived, single-use ticket carrying only the caller's
    timezone. The caller is identified later, in-conversation, by the agent.
    """
    timezone = req.timezone if req else None
    table_token = req.table_token if req else None
    ticket = auth_service.issue_ws_ticket(timezone=timezone, table_token=table_token)
    return TicketResponse(ticket=ticket)
