"""TableSession repository."""

from sqlalchemy.orm import Session

from db.models.table_session import TableSession


class TableSessionRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, session_id: str) -> TableSession | None:
        return self.db.get(TableSession, session_id)

    def get_open_for_table(self, table_id: str) -> TableSession | None:
        """The one live tab for a table, if any (status not yet closed)."""
        return (
            self.db.query(TableSession)
            .filter(
                TableSession.table_id == table_id,
                TableSession.status != "closed",
            )
            .order_by(TableSession.opened_at.desc())
            .first()
        )

    def list_active(self) -> list[TableSession]:
        """All open/billed tabs across the floor (for the live floor map)."""
        return (
            self.db.query(TableSession)
            .filter(TableSession.status != "closed")
            .order_by(TableSession.opened_at)
            .all()
        )

    def create(self, **kwargs) -> TableSession:
        session = TableSession(**kwargs)
        self.db.add(session)
        self.db.flush()
        return session

    def update(self, session_id: str, **kwargs) -> TableSession | None:
        session = self.get_by_id(session_id)
        if not session:
            return None
        for key, value in kwargs.items():
            setattr(session, key, value)
        self.db.flush()
        return session
