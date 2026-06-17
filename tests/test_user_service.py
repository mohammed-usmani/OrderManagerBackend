import pytest
from services.user_service import UserService


def test_register_creates_user(db):
    service = UserService(db)
    user = service.register("new@example.com", "password123", "New User")
    assert user.id is not None
    assert user.email == "new@example.com"
    assert user.hashed_password != "password123"  # must be hashed


def test_register_duplicate_email_raises(db):
    service = UserService(db)
    service.register("dup@example.com", "password1", "User")
    with pytest.raises(ValueError, match="already registered"):
        service.register("dup@example.com", "password2", "User2")


def test_validate_registration_rules():
    from services.user_service import validate_registration
    with pytest.raises(ValueError, match="at least"):
        validate_registration("short@example.com", "pass", "User")
    with pytest.raises(ValueError, match="valid email"):
        validate_registration("not-an-email", "password123", "User")
    validate_registration("ok@example.com", "password123", "User")  # no raise


def test_login_valid_credentials(db):
    service = UserService(db)
    service.register("login@example.com", "secret12", "Login User")
    user = service.login("login@example.com", "secret12")
    assert user.email == "login@example.com"


def test_login_wrong_password_raises(db):
    service = UserService(db)
    service.register("wrong@example.com", "correct1", "User")
    with pytest.raises(ValueError, match="Invalid credentials"):
        service.login("wrong@example.com", "wrongpass")


def test_login_unknown_email_raises(db):
    service = UserService(db)
    with pytest.raises(ValueError, match="Invalid credentials"):
        service.login("nobody@example.com", "pass")
