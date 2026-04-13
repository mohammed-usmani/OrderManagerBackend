from services.chat_service import ChatService
from services.order_service import OrderService
from services.user_service import UserService
import uuid


def _make_user_and_cart(db):
    email = f"{uuid.uuid4()}@chat.com"
    user = UserService(db).register(email, "pass", "Chat User")
    cart = OrderService(db).get_or_create_cart(user.id)
    return user, cart


def test_get_active_session_returns_session(db):
    user, cart = _make_user_and_cart(db)
    service = ChatService(db)
    session = service.get_active_session(user.id)
    assert session is not None
    assert session.order_id == cart.id


def test_save_and_retrieve_messages(db):
    user, _ = _make_user_and_cart(db)
    service = ChatService(db)
    session = service.get_active_session(user.id)

    service.save_message(session.id, "user", "I'd like to order")
    service.save_message(session.id, "assistant", "Of course!")

    history = service.get_history(session.id)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].content == "Of course!"


def test_get_history_as_langchain_messages(db):
    user, _ = _make_user_and_cart(db)
    service = ChatService(db)
    session = service.get_active_session(user.id)
    service.save_message(session.id, "user", "Hello")
    service.save_message(session.id, "assistant", "Hi there")

    messages = service.get_history_as_langchain_messages(session.id)
    assert len(messages) == 2
    from langchain_core.messages import HumanMessage, AIMessage
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)


def test_close_session(db):
    user, _ = _make_user_and_cart(db)
    service = ChatService(db)
    session = service.get_active_session(user.id)
    service.close_session(session.id)

    assert service.get_active_session(user.id) is None
