import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost/restaurant_test"


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    from db.base import Base
    import db.models.user  # noqa: F401
    import db.models.menu  # noqa: F401
    import db.models.order  # noqa: F401
    import db.models.chat  # noqa: F401

    test_engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
def db():
    from db.base import Base
    test_engine = create_engine(TEST_DATABASE_URL)
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    yield session
    session.rollback()
    session.close()
