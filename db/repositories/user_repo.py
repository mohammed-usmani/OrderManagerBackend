"""User repository — raw DB queries for User model."""

from sqlalchemy.orm import Session

from db.models.user import User


class UserRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email).first()

    def create(self, email: str, hashed_password: str, name: str, is_admin: bool = False) -> User:
        user = User(email=email, hashed_password=hashed_password, name=name, is_admin=is_admin)
        self.db.add(user)
        self.db.flush()
        return user

    def email_exists(self, email: str) -> bool:
        return self.db.query(User).filter(User.email == email).count() > 0
