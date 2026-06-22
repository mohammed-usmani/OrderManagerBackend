import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = "postgresql://mohammed:mohammed%40123@localhost/restaurant_test"

# Set True once the schema is created. DB-backed tests skip when it's False
# (e.g. the pgvector extension can't be enabled without a superuser locally).
_db_ready = False


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    global _db_ready
    from db.base import Base
    import db.models.user  # noqa: F401
    import db.models.menu  # noqa: F401
    import db.models.order  # noqa: F401
    import db.models.chat  # noqa: F401
    import db.models.customer  # noqa: F401
    import db.models.service_area  # noqa: F401
    import db.models.floor  # noqa: F401
    import db.models.dining_zone  # noqa: F401
    import db.models.restaurant_table  # noqa: F401
    import db.models.table_session  # noqa: F401
    import db.models.audit_log  # noqa: F401

    test_engine = create_engine(TEST_DATABASE_URL)
    try:
        # menu_items.embedding is a pgvector column, so the extension must exist
        # before create_all. Requires a superuser (or a Render-style grant).
        with test_engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(test_engine)
        _db_ready = True
        yield
        Base.metadata.drop_all(test_engine)
    except Exception as e:  # keep DB-free tests runnable; DB tests skip
        print(f"[conftest] Test DB unavailable, DB-backed tests will skip: {e}")
        yield


@pytest.fixture
def db():
    if not _db_ready:
        pytest.skip("test DB not ready (pgvector extension / superuser required)")
    from sqlalchemy.orm import Session  # noqa: F401
    test_engine = create_engine(TEST_DATABASE_URL)
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    yield session
    session.rollback()
    session.close()
