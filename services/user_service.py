"""User service: registration and login."""

import re

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from db.models.user import User
from db.repositories.user_repo import UserRepo
from services.roles import ALL_ROLES, NONE, is_admin_role

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


def validate_registration(email: str, password: str, name: str) -> None:
    """Public sign-up input policy (enforced at the API boundary, not on the
    internal register() path so seeding/admin provisioning isn't constrained)."""
    if not _EMAIL_RE.match((email or "").strip().lower()):
        raise ValueError("Enter a valid email address")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if not (name or "").strip():
        raise ValueError("Name is required")


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepo(db)

    def register(self, email: str, password: str, name: str, role: str = NONE) -> User:
        if self.repo.email_exists(email):
            raise ValueError(f"{email} is already registered")
        if role not in ALL_ROLES:
            raise ValueError(f"Unknown role '{role}'")
        hashed = _pwd_context.hash(password)
        # is_admin stays derived from the role so existing admin-gated endpoints
        # keep working without per-endpoint rewrites.
        return self.repo.create(
            email=email,
            hashed_password=hashed,
            name=name,
            is_admin=is_admin_role(role),
            role=role,
        )

    def login(self, email: str, password: str) -> User:
        user = self.repo.get_by_email(email)
        if not user or not _pwd_context.verify(password, user.hashed_password):
            raise ValueError("Invalid credentials")
        return user

    def list_staff(self) -> list[User]:
        return self.repo.list_staff()

    def set_role(self, user_id: str, role: str) -> User:
        if role not in ALL_ROLES:
            raise ValueError(f"Unknown role '{role}'")
        user = self.repo.update(user_id, role=role, is_admin=is_admin_role(role))
        if not user:
            raise ValueError("User not found")
        return user

    def delete(self, user_id: str) -> None:
        if not self.repo.delete(user_id):
            raise ValueError("User not found")
