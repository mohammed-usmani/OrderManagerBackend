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


def test_role_drives_is_admin(db):
    service = UserService(db)
    owner = service.register("owner@x.com", "password1", "Owner", role="owner")
    manager = service.register("mgr@x.com", "password1", "Mgr", role="manager")
    cashier = service.register("cash@x.com", "password1", "Cash", role="cashier")
    chef = service.register("chef@x.com", "password1", "Chef", role="chef")
    assert owner.is_admin is True and owner.role == "owner"
    assert manager.is_admin is True
    assert cashier.is_admin is False and cashier.role == "cashier"
    assert chef.is_admin is False
    # Public signup default is non-staff.
    public = service.register("guest@x.com", "password1", "Guest")
    assert public.role == "none" and public.is_admin is False


def test_set_role_updates_is_admin(db):
    service = UserService(db)
    u = service.register("flip@x.com", "password1", "Flip", role="waiter")
    assert u.is_admin is False
    u2 = service.set_role(u.id, "manager")
    assert u2.is_admin is True and u2.role == "manager"


def test_register_rejects_unknown_role(db):
    service = UserService(db)
    with pytest.raises(ValueError, match="Unknown role"):
        service.register("bad@x.com", "password1", "Bad", role="superuser")
