import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Make server/ importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

load_dotenv()

# Import all models so Alembic sees them
from db.base import Base  # noqa: E402
import db.models.user  # noqa: F401, E402
import db.models.menu  # noqa: F401, E402
import db.models.order  # noqa: F401, E402
import db.models.chat  # noqa: F401, E402
import db.models.customer  # noqa: F401, E402
import db.models.service_area  # noqa: F401, E402
import db.models.floor  # noqa: F401, E402
import db.models.dining_zone  # noqa: F401, E402
import db.models.restaurant_table  # noqa: F401, E402
import db.models.table_session  # noqa: F401, E402
import db.models.app_setting  # noqa: F401, E402

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
