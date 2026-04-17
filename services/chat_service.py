"""Chat service: session management and message persistence."""

from datetime import datetime

from sqlalchemy.orm import Session

from db.models.chat import ChatMessage, ChatSession
from db.repositories.chat_repo import ChatRepo


class ChatService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ChatRepo(db)

    def get_active_session(self, user_id: str) -> ChatSession | None:
        return self.repo.get_active_session_for_user(user_id)

    def get_or_create_session(self, user_id: str, order_id: str) -> ChatSession:
        session = self.repo.get_active_session_for_user(user_id)
        if session:
            return session
        return self.repo.create_session(user_id=user_id, order_id=order_id)

    def save_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        return self.repo.add_message(session_id=session_id, role=role, content=content)

    def get_history(self, session_id: str) -> list[ChatMessage]:
        return self.repo.get_messages(session_id)

    def close_session(self, session_id: str) -> None:
        session = self.repo.get_session_by_id(session_id)
        if session:
            session.status = "closed"
            session.closed_at = datetime.utcnow()
            self.db.flush()

    def get_sessions_for_user(self, user_id: str) -> list[ChatSession]:
        return self.repo.get_sessions_for_user(user_id)
