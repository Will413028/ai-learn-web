from alembic import context
from app.db import Base, Database
from app.settings import from_environment

supplied = context.config.attributes.get("connection")
if supplied is not None:
    context.configure(connection=supplied, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    db = Database(from_environment().database_url)
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    db.close()
