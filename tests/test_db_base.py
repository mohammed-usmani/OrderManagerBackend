from db.base import get_session


def test_get_session_connects():
    with get_session() as db:
        from sqlalchemy import text
        result = db.execute(text("SELECT 1")).scalar()
    assert result == 1
