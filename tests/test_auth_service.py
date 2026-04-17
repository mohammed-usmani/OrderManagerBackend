import pytest
from unittest.mock import MagicMock
from services.auth_service import AuthService


@pytest.fixture
def auth_service():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    return AuthService(redis_client=mock_redis)


def test_create_and_decode_token(auth_service):
    token = auth_service.create_access_token("user-123", "a@b.com", is_admin=False)
    payload = auth_service.decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["email"] == "a@b.com"
    assert payload["is_admin"] is False


def test_decode_invalid_token_raises(auth_service):
    with pytest.raises(ValueError, match="Invalid token"):
        auth_service.decode_token("not.a.jwt")


def test_issue_and_consume_ws_ticket(auth_service):
    import json
    auth_service.redis.get.return_value = json.dumps(
        {"user_id": "user-123", "timezone": "Asia/Kolkata"}
    ).encode()
    ticket = auth_service.issue_ws_ticket("user-123", timezone="Asia/Kolkata")
    assert ticket is not None

    payload = auth_service.consume_ws_ticket(ticket)
    assert payload == {"user_id": "user-123", "timezone": "Asia/Kolkata"}


def test_consume_legacy_ticket_returns_user_id(auth_service):
    # Back-compat: old tickets stored the raw user_id string.
    auth_service.redis.get.return_value = b"user-legacy"
    payload = auth_service.consume_ws_ticket("t")
    assert payload == {"user_id": "user-legacy", "timezone": None}


def test_consume_expired_ticket_returns_none(auth_service):
    auth_service.redis.get.return_value = None
    result = auth_service.consume_ws_ticket("nonexistent-ticket")
    assert result is None
