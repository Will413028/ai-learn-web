from collections.abc import Iterator
from pathlib import Path
import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text

from app.db import Base, Database
from app.main import create_app
from app.network_guard import install
from app.settings import Settings

ORIGIN = "http://127.0.0.1:3100"


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[Database]:
    name = f"ai_learn_test_{uuid4().hex}"
    port = int(os.getenv("TEST_DATABASE_PORT", "55483"))
    admin = create_engine(f"postgresql+psycopg://ai_learn@127.0.0.1:{port}/ai_learn",
                          isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = f"postgresql+psycopg://ai_learn@127.0.0.1:{port}/{name}"
    db = Database(url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    # The migration accepts an explicit connection so test databases never use environment URLs.
    try:
        with db.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield db
    finally:
        db.close()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def database(migrated_database: Database) -> Iterator[Database]:
    tables = ",".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with migrated_database.engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    yield migrated_database


@pytest.fixture
def app(database: Database, tmp_path: Path) -> FastAPI:
    return create_app(database=database, settings=Settings(asset_directory=tmp_path))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers={"origin": ORIGIN}) as c:
        yield c


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    monkeypatch.setenv("AI_TEST_BLOCK_EXTERNAL", "1")
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, getattr(socket.socket, name))
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, getattr(socket, name))
    install()
