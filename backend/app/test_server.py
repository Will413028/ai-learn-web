from app.network_guard import install

install()

if __name__ == "__main__":
    import os
    from pathlib import Path
    from tempfile import TemporaryDirectory
    import threading
    from uuid import uuid4

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    import uvicorn

    from app.db import Database
    from app.main import create_app
    from app.settings import Settings

    port = int(os.getenv("TEST_DATABASE_PORT", "55483"))
    name = f"ai_learn_e2e_{uuid4().hex}"
    admin = create_engine(f"postgresql+psycopg://ai_learn@127.0.0.1:{port}/ai_learn",
                          isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    db = Database(f"postgresql+psycopg://ai_learn@127.0.0.1:{port}/{name}")
    stop = threading.Event()
    worker = None
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with db.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with TemporaryDirectory(prefix="ai-learn-e2e-") as directory:
            application = create_app(database=db, settings=Settings(asset_directory=Path(directory)))

            def run_worker() -> None:
                while not stop.is_set():
                    if not application.state.worker.run_once():
                        stop.wait(0.1)

            worker = threading.Thread(target=run_worker, daemon=True)
            worker.start()
            uvicorn.run(application, host="127.0.0.1", port=8100, timeout_keep_alive=65)
            stop.set()
            worker.join(timeout=35)
    finally:
        stop.set()
        if worker:
            worker.join(timeout=35)
        db.close()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
