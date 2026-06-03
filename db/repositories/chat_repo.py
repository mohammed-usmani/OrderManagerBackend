"""ChatSession and ChatMessage repository."""

from sqlalchemy.orm import Session

from db.models.chat import ChatMessage, ChatSession


class ChatRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_session_by_id(self, session_id: str) -> ChatSession | None:
        return self.db.get(ChatSession, session_id)

    def get_active_session_for_user(self, user_id: str) -> ChatSession | None:
        return (
            self.db.query(ChatSession)
            .filter(ChatSession.user_id == user_id, ChatSession.status == "active")
            .first()
        )

    def get_session_for_order(self, order_id: str) -> ChatSession | None:
        return (
            self.db.query(ChatSession)
            .filter(ChatSession.order_id == order_id)
            .first()
        )

    def get_sessions_for_user(self, user_id: str) -> list[ChatSession]:
        return (
            self.db.query(ChatSession)
            .filter(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
            .all()
        )

    def create_session(
        self,
        order_id: str,
        user_id: str | None = None,
        customer_id: str | None = None,
    ) -> ChatSession:
        session = ChatSession(
            user_id=user_id, customer_id=customer_id, order_id=order_id
        )
        self.db.add(session)
        self.db.flush()
        return session

    def add_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        msg = ChatMessage(session_id=session_id, role=role, content=content)
        self.db.add(msg)
        self.db.flush()
        return msg

    def get_messages(self, session_id: str) -> list[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
            .all()
        )
