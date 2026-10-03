from datetime import timedelta
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.db import Database, Document, Job
from tests.test_learning import generated, register
from tests.test_resources import reserve


@pytest.mark.parametrize("path,method", [("/quiz/not-a-uuid", "GET"), ("/jobs/not-a-uuid", "GET"),
    ("/documents/not-a-uuid", "GET"), ("/assets/not-a-uuid", "GET"),
    ("/quiz/not-a-uuid/answers", "POST"), ("/assets/not-a-uuid", "DELETE")])
def test_malformed_resource_id_is_rejected_before_sql(client: TestClient, path: str, method: str) -> None:
    response = client.request(method, f"/api/v1{path}", **({"json": {}} if method != "GET" else {}))
    assert response.status_code == 422


def test_guest_and_user_same_request_key_can_be_claimed(client: TestClient, app: FastAPI, database: Database) -> None:
    guest = client.post("/api/v1/quiz/generate", json={"topic": "Guest Python"},
                        headers={"Idempotency-Key": "same"}).json()
    register(client)
    user = client.post("/api/v1/quiz/generate", json={"topic": "User Python"},
                       headers={"Idempotency-Key": "same"}).json()
    session = client.get("/api/v1/session").json()
    assert session["claimable_quizzes"] == 0 and session["claimable_jobs"] == 1
    assert client.post("/api/v1/auth/claim", json={}).json() == {"quizzes": 0, "experience": 0, "jobs": 1}
    assert client.get(f"/api/v1/jobs/{guest['id']}").status_code == 200
    assert client.get(f"/api/v1/jobs/{user['id']}").status_code == 200
    repeated = client.post("/api/v1/quiz/generate", json={"topic": "User Python"},
                           headers={"Idempotency-Key": "same"}).json()
    assert repeated["id"] == user["id"]
    app.state.worker.run_once()
    app.state.worker.run_once()
    with database.transaction() as db_session:
        jobs = list(db_session.scalars(select(Job)))
        assert len(jobs) == 2 and len({job.owner_id for job in jobs}) == 1
        assert len({job.request_scope_id for job in jobs}) == 2


def test_partial_staging_is_removed_on_storage_failure(client: TestClient, app: FastAPI,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    register(client)
    quiz = generated(client)
    asset = reserve(client, quiz["id"]).json()
    original = Path.write_bytes

    def partial_write(path: Path, data: bytes) -> int:
        if path.name.endswith(".staging"):
            original(path, data[:32])
            raise OSError("test-only partial write")
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", partial_write)
    assert app.state.worker.run_once()
    assert client.get(f"/api/v1/assets/{asset['id']}").json()["status"] == "failed"
    directory = app.state.resources.path("images", asset["id"]).parent
    assert list(directory.iterdir()) == []


def test_reconcile_skips_inflight_uncommitted_upload(client: TestClient, app: FastAPI, database: Database) -> None:
    user = register(client)
    document_id = str(uuid4())
    path = app.state.resources.path("documents", document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    db_session = database.sessions()
    transaction = db_session.begin()
    try:
        db_session.add(Document(id=document_id, owner_id=user["id"], filename="x.txt", size=6,
            status="pending", created_at=app.state.auth.now()))
        db_session.flush()
        app.state.resources.lock_file(db_session, document_id)
        path.write_bytes(b"Python")
        assert app.state.resources.reconcile_files(minimum_age_seconds=0) == 0
        assert path.exists()
    finally:
        transaction.rollback()
        db_session.close()
    assert app.state.resources.reconcile_files(minimum_age_seconds=0) == 1
    assert not path.exists()


def test_process_exit_before_image_commit_is_reconciled(client: TestClient, app: FastAPI, database: Database) -> None:
    register(client)
    quiz = generated(client)
    asset = reserve(client, quiz["id"]).json()
    claimed = app.state.worker.claim()
    assert claimed
    job_id, version, *_ = claimed
    with database.transaction() as session:
        job = session.get(Job, job_id)
        assert job
        job.lease_until = app.state.auth.now() + timedelta(minutes=15)
    code = """
import os
from pathlib import Path
from sqlalchemy import event
from app.db import Database
from app.auth import Auth
from app.providers import FakeProvider
from app.settings import Settings
from app.worker import Worker
db = Database(os.environ['CRASH_TEST_DB'])
settings = Settings(asset_directory=Path(os.environ['CRASH_TEST_ASSETS']))
worker = Worker(db, Auth(db, settings), FakeProvider(), settings)
@event.listens_for(db.engine, 'commit')
def exit_before_commit(connection):
    os._exit(73)
worker.finish(os.environ['CRASH_TEST_JOB'], int(os.environ['CRASH_TEST_VERSION']),
              result=FakeProvider().image('test-only fixture'))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "CRASH_TEST_DB": database.engine.url.render_as_string(hide_password=False),
             "CRASH_TEST_ASSETS": str(app.state.resources.settings.asset_directory),
             "CRASH_TEST_JOB": job_id, "CRASH_TEST_VERSION": str(version)},
        capture_output=True, timeout=120)
    assert result.returncode == 73
    path = app.state.resources.path("images", asset["id"])
    assert path.is_file()
    assert client.get(f"/api/v1/assets/{asset['id']}/content").status_code == 409
    with database.transaction() as session:
        job = session.get(Job, job_id)
        assert job and job.status == "running"
        job.lease_until = app.state.auth.now() - timedelta(seconds=1)
    assert app.state.worker.recover() == 1
    assert app.state.resources.reconcile_files(minimum_age_seconds=0) == 1
    assert not path.exists()


def test_reconcile_keeps_ready_documents_and_completed_images(client: TestClient, app: FastAPI) -> None:
    register(client)
    document = client.post("/api/v1/documents", files={"file": ("x.txt", b"Python")}).json()
    app.state.worker.run_once()
    quiz = generated(client)
    asset = reserve(client, quiz["id"]).json()
    app.state.worker.run_once()
    assert app.state.resources.reconcile_files(minimum_age_seconds=0) == 0
    assert app.state.resources.path("documents", document["id"]).exists()
    assert app.state.resources.path("images", asset["id"]).exists()


def test_concurrent_claim_awards_guest_xp_once(client, app, database) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from tests.test_learning import complete, generated, register
    quiz = generated(client)
    complete(client, quiz)
    register(client)
    requests = [client.build_request("POST", "/api/v1/auth/claim", json={}) for _ in range(2)]
    barrier = Barrier(2)
    def send(request):
        barrier.wait(timeout=10)
        return client.send(request).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(send, requests))
    assert sorted(statuses) == [200, 409]
    assert client.get("/api/v1/user/profile").json()["experience"] == 25


def test_parallel_worker_claims_are_unique(client, app, database) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    for i in range(6):
        response = client.post("/api/v1/quiz/generate", json={"topic": f"Worker {i}"},
                               headers={"Idempotency-Key": f"parallel-{i}"})
        assert response.status_code == 202
    barrier = Barrier(6)
    def claim(_):
        barrier.wait(timeout=10)
        return app.state.worker.claim()
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(claim, range(6)))
    assert all(claim is not None for claim in claims)
    assert len({claim[0] for claim in claims}) == 6
    assert app.state.worker.claim() is None
