"""Auth router: register, login, ws-ticket."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import get_current_user
from services.auth_service import auth_service
from services.user_service import UserService

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


class TicketResponse(BaseModel):
    ticket: str


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = UserService(db).register(req.email, req.password, req.name)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    token = auth_service.create_access_token(user.id, user.email, user.is_admin)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = UserService(db).login(req.email, req.password)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = auth_service.create_access_token(user.id, user.email, user.is_admin)
    return TokenResponse(access_token=token)


@router.post("/ws-ticket", response_model=TicketResponse)
def ws_ticket(current_user=Depends(get_current_user)):
    ticket = auth_service.issue_ws_ticket(current_user.id)
    return TicketResponse(ticket=ticket)
