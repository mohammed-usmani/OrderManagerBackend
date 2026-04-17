"""Chat router: read session history."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import get_current_user
from services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str

    model_config = {"from_attributes": True}


class ChatSessionResponse(BaseModel):
    id: str
    order_id: str
    status: str
    created_at: str
    messages: list[ChatMessageResponse] = []

    model_config = {"from_attributes": True}


@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_sessions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    sessions = ChatService(db).get_sessions_for_user(current_user.id)
    return [
        ChatSessionResponse(
            id=s.id,
            order_id=s.order_id,
            status=s.status,
            created_at=s.created_at.isoformat(),
            messages=[],
        )
        for s in sessions
    ]


@router.get("/sessions/active", response_model=ChatSessionResponse | None)
def get_active_session(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the user's currently active chat session + messages, or null."""
    session = ChatService(db).get_active_session(current_user.id)
    if not session:
        return None
    messages = [
        ChatMessageResponse(
            id=m.id, role=m.role, content=m.content, created_at=m.created_at.isoformat()
        )
        for m in session.messages
    ]
    return ChatSessionResponse(
        id=session.id,
        order_id=session.order_id,
        status=session.status,
        created_at=session.created_at.isoformat(),
        messages=messages,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from db.repositories.chat_repo import ChatRepo

    session = ChatRepo(db).get_session_by_id(session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    messages = [
        ChatMessageResponse(
            id=m.id, role=m.role, content=m.content, created_at=m.created_at.isoformat()
        )
        for m in session.messages
    ]
    return ChatSessionResponse(
        id=session.id,
        order_id=session.order_id,
        status=session.status,
        created_at=session.created_at.isoformat(),
        messages=messages,
    )
