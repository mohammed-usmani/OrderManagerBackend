"""User service: registration and login."""

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from db.models.user import User
from db.repositories.user_repo import UserRepo

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepo(db)

    def register(self, email: str, password: str, name: str, is_admin: bool = False) -> User:
        if self.repo.email_exists(email):
            raise ValueError(f"{email} is already registered")
        hashed = _pwd_context.hash(password)
        return self.repo.create(email=email, hashed_password=hashed, name=name, is_admin=is_admin)

    def login(self, email: str, password: str) -> User:
        user = self.repo.get_by_email(email)
        if not user or not _pwd_context.verify(password, user.hashed_password):
            raise ValueError("Invalid credentials")
        return user
