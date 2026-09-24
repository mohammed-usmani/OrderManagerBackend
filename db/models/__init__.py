"""Model registry: importing `db.models` registers every table on Base.metadata.

Alembic (migrations/env.py) and the test schema (tests/conftest.py) both rely on
this, so add new model modules here.
"""

from db.models import (  # noqa: F401
    app_setting,
    audit_log,
    chat,
    customer,
    dining_zone,
    floor,
    menu,
    order,
    payment,
    restaurant_table,
    service_area,
    table_session,
    user,
)
