import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Defaults to the docker-compose database (`docker compose up -d db`).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/restaurant_test"
)

# Point the app itself at the test database/Redis before anything imports `config`,
# so TestClient(app) startup seeding and background work never touch .env's DB.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")
# Tests seed what they need inside their own rolled-back transaction.
os.environ["SEED_ON_STARTUP"] = "false"

# Set True once the schema is created. DB-backed tests skip when it's False
# (e.g. the pgvector extension can't be enabled without a superuser locally).
_db_ready = False


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    global _db_ready
    from db.base import Base
    import db.models  # noqa: F401  # registers every model

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


@pytest.fixture(scope="session", autouse=True)
def _fresh_test_redis():
    """Clear the tests' own Redis index so lockouts/tickets don't carry over runs."""
    import redis

    try:
        redis.Redis.from_url(os.environ["REDIS_URL"]).flushdb()
    except redis.RedisError as e:
        print(f"[conftest] Test Redis unavailable: {e}")
    yield


@pytest.fixture
def db():
    if not _db_ready:
        pytest.skip("test DB not ready (pgvector extension / superuser required)")
    from sqlalchemy.orm import Session

    # One outer transaction per test; commits inside the code under test (e.g.
    # router handlers) become savepoints, so everything is rolled back after.
    test_engine = create_engine(TEST_DATABASE_URL)
    connection = test_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    outer.rollback()
    connection.close()
