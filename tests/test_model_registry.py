"""Every model must be registered through `db.models`, or Alembic autogenerate
proposes dropping its table and the test schema silently lacks it."""

import ast
import pathlib

import db.models  # noqa: F401 — the registry under test
from db.base import Base


def test_every_model_module_is_registered():
    tables = set()
    for path in pathlib.Path("db/models").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__tablename__" for t in node.targets
            ):
                tables.add(node.value.value)
    assert tables, "no models found"
    assert tables <= set(Base.metadata.tables), tables - set(Base.metadata.tables)


def test_alembic_and_tests_use_the_registry():
    for path in ("migrations/env.py", "tests/conftest.py"):
        assert "import db.models\n" in pathlib.Path(path).read_text() or \
               "import db.models  #" in pathlib.Path(path).read_text(), path
