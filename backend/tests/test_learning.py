from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import socket
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.db import Answer, Database, Job, Quiz, User
from app.main import create_app
from app.providers import FakeProvider
from app.schemas import GenerateRequest
from app.settings import Settings
from tests.conftest import ORIGIN


def generated(client: TestClient, **extra: Any) -> dict[str, Any]:
    response = client.post("/api/v1/quiz/generate", json={"topic": "Python", **extra},
                           headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 202, response.text
    job = response.json()
    worker = client.app.state.worker  # type: ignore[union-attr]
    for _ in range(10):
        worker.run_once()
        status = client.get(f"/api/v1/jobs/{job['id']}").json()
        if status["status"] == "completed":
            return client.get(f"/api/v1/quiz/{status['result_id']}").json()  # type: ignore[no-any-return]
        if status["status"] == "failed":
            raise AssertionError(status)
    raise AssertionError("job did not complete")


def submit(client: TestClient, quiz: dict[str, Any], question: dict[str, Any],
           selected: list[str], **extra: Any) -> Any:
    return client.post(f"/api/v1/quiz/{quiz['id']}/answers", json={
        "question_id": question["id"], "selected_answers": selected, "duration_ms": 1200, **extra})


def complete(client: TestClient, quiz: dict[str, Any], wrong: bool = False) -> None:
    for q in quiz["questions"]:
        selected = ["A"] if wrong and q["type"] != "boolean" else {
            "single": ["B"], "multiple": ["A", "B"], "boolean": ["T"]}[q["type"]]
        assert submit(client, quiz, q, selected).status_code == 200


def register(client: TestClient, email: str = "learner@example.com") -> dict[str, Any]:
    response = client.post("/api/v1/auth/register", json={"email": email,
        "password": "test-only-password-123", "nickname": "Learner"})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_three_types_and_server_report(client: TestClient) -> None:
    quiz = generated(client)
    assert {q["type"] for q in quiz["questions"]} == {"single", "multiple", "boolean"}
    for q in quiz["questions"]:
        assert set(q) == {"id", "type", "text", "options"}
    assert client.post(f"/api/v1/quiz/{quiz['id']}/report", json={}).status_code == 409
    complete(client, quiz)
    report = client.post(f"/api/v1/quiz/{quiz['id']}/report", json={}).json()
    assert (report["accuracy"], report["correct"], report["experience"], report["duration_ms"]) == (100.0, 3, 25, 3600)
    assert report["narrative"]["mastery"]
    assert client.post(f"/api/v1/quiz/{quiz['id']}/report", json={"is_correct": True}).status_code == 422


def test_report_accuracy_calculated_from_answers(client: TestClient) -> None:
    quiz = generated(client)
    complete(client, quiz, wrong=True)
    response = client.post(f"/api/v1/quiz/{quiz['id']}/report", json={})
    assert response.status_code == 200
    result = response.json()
    assert (result["correct"], result["total"], result["accuracy"], result["experience"]) == (1, 3, 33.33, 15)
    assert client.post(f"/api/v1/quiz/{quiz['id']}/report", json={}).json() == result


@pytest.mark.parametrize("kind,selected,expected", [
    ("single", ["A"], False), ("single", ["B"], True),
    ("multiple", ["A"], False), ("multiple", ["B", "A"], True),
    ("multiple", ["A", "B", "C"], False), ("boolean", ["F"], False), ("boolean", ["T"], True)])
def test_exact_scoring(client: TestClient, kind: str, selected: list[str], expected: bool) -> None:
    quiz = generated(client, question_count=1, question_types=[kind])
    assert submit(client, quiz, quiz["questions"][0], selected).json()["is_correct"] is expected


@pytest.mark.parametrize("extra", [{"is_correct": True}, {"selected_answers": ["Z"]},
    {"selected_answers": ["B", "B"]}, {"duration_ms": -1}, {"duration_ms": "1"},
    {"question_id": "other"}, {"selected_answers": ["A", "B"]}])
def test_invalid_answers(client: TestClient, extra: dict[str, Any]) -> None:
    quiz = generated(client, question_count=1, question_types=["single"])
    assert submit(client, quiz, quiz["questions"][0], ["B"], **extra).status_code == 422


def test_concurrent_answers_fixed_and_xp_once(client: TestClient, database: Database) -> None:
    user = register(client)
    quiz = generated(client, question_count=1, question_types=["single"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda choice: submit(client, quiz, quiz["questions"][0], [choice]).status_code, ["A", "B"]))
    assert sorted(codes) == [200, 409]
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Answer)) == 1
        stored = session.get(User, user["id"])
        assert stored is not None and stored.experience in {10, 15}
        experience = stored.experience
    answer = client.post(f"/api/v1/quiz/{quiz['id']}/report", json={}).json()["answers"][0]
    again = submit(client, quiz, quiz["questions"][0], answer["selected_answers"], duration_ms=9999)
    assert again.json()["duration_ms"] == 1200
    assert client.get("/api/v1/user/profile").json()["experience"] == experience


def test_quiz_job_history_owner_isolation(client: TestClient, app: FastAPI) -> None:
    quiz = generated(client)
    with TestClient(app, headers={"origin": ORIGIN}) as other:
        other.get("/api/v1/session")
        assert other.get(f"/api/v1/quiz/{quiz['id']}").status_code == 404
        assert other.post(f"/api/v1/quiz/{quiz['id']}/report", json={}).status_code == 404
        assert other.get("/api/v1/user/quizzes").json()["total"] == 0
    assert client.get("/api/v1/user/quizzes").json()["total"] == 1


@pytest.mark.parametrize("origin", [None, "null", "https://evil.invalid"])
def test_csrf_before_side_effects(app: FastAPI, database: Database, origin: str | None) -> None:
    with TestClient(app) as c:
        headers = {"Idempotency-Key": "csrf"}
        if origin:
            headers["origin"] = origin
        assert c.post("/api/v1/quiz/generate", json={"topic": "Python"}, headers=headers).status_code == 403
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


def test_register_login_logout_rotation(client: TestClient, app: FastAPI, database: Database) -> None:
    user = register(client)
    with database.transaction() as session:
        stored = session.get(User, user["id"])
        assert stored is not None and stored.password_hash.startswith("$argon2id$")
    assert client.post("/api/v1/auth/logout", json={}).status_code == 204
    assert client.get("/api/v1/user/profile").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": user["email"], "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": user["email"], "password": "test-only-password-123"}).status_code == 200
    client.put("/api/v1/user/profile", json={"nickname": "Updated", "avatar_url": "https://example.com/avatar.png"})
    profile = client.get("/api/v1/user/profile").json()
    assert profile["nickname"] == "Updated" and profile["avatar_url"].endswith("avatar.png")
    assert client.post("/api/v1/auth/register", json={"email": user["email"], "password": "test-only-password-123", "nickname": "Other"}).status_code == 409


def test_failed_login_rate_limit_commits(client: TestClient) -> None:
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json={"email": "none@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "none@example.com", "password": "wrong"}).status_code == 429


def test_explicit_guest_claim_once(client: TestClient, database: Database) -> None:
    quiz = generated(client)
    complete(client, quiz)
    register(client)
    assert client.get("/api/v1/session").json()["claimable_quizzes"] == 1
    claim = client.post("/api/v1/auth/claim", json={})
    assert claim.json() == {"quizzes": 1, "experience": 25, "jobs": 1}
    assert client.post("/api/v1/auth/claim", json={}).status_code == 409
    assert client.get("/api/v1/user/profile").json()["experience"] == 25
    assert client.get(f"/api/v1/quiz/{quiz['id']}").status_code == 200


def test_guest_expiry_and_cleanup(database: Database, tmp_path: Path) -> None:
    now = [1000.0]
    app = create_app(database=database, settings=Settings(asset_directory=tmp_path), clock=lambda: now[0])
    with TestClient(app, headers={"origin": ORIGIN}) as c:
        quiz = generated(c)
        now[0] += 7 * 86400
        assert c.get(f"/api/v1/quiz/{quiz['id']}").status_code == 401
        assert app.state.auth.cleanup() == 1
        with database.transaction() as session:
            assert session.scalar(select(func.count()).select_from(Quiz)) == 0


def test_job_idempotency_restart_and_fencing(client: TestClient, app: FastAPI, database: Database) -> None:
    body = {"topic": "Python"}
    headers = {"Idempotency-Key": "same"}
    first = client.post("/api/v1/quiz/generate", json=body, headers=headers).json()
    assert client.post("/api/v1/quiz/generate", json=body, headers=headers).json()["id"] == first["id"]
    assert client.post("/api/v1/quiz/generate", json={"topic": "different"}, headers=headers).status_code == 409
    claim = app.state.worker.claim()
    assert claim is not None
    job_id, version, owner, kind, payload = claim
    result = app.state.worker.process(kind, owner, payload)
    with database.transaction() as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.lease_until = app.state.auth.now() - timedelta(seconds=1)
    assert app.state.worker.recover() == 1
    assert not app.state.worker.finish(job_id, version, result)
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Quiz)) == 0
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "failed"
    retry = client.post(f"/api/v1/jobs/{job_id}/retry", json={}, headers={"Idempotency-Key": "retry"})
    assert retry.status_code == 202 and retry.json()["id"] != job_id
    app.state.worker.run_once()
    assert client.get(f"/api/v1/jobs/{retry.json()['id']}").json()["status"] == "completed"


def test_bad_provider_marks_job_failed(database: Database, tmp_path: Path) -> None:
    class Broken(FakeProvider):
        def generate(self, request: GenerateRequest, context: str, *, deadline: float = float("inf")) -> object:
            return {"questions": [{"id": "bad"}]}
    app = create_app(provider=Broken(), database=database, settings=Settings(asset_directory=tmp_path))
    with TestClient(app, headers={"origin": ORIGIN}) as c:
        job = c.post("/api/v1/quiz/generate", json={"topic": "Python"}, headers={"Idempotency-Key": "bad"}).json()
        app.state.worker.run_once()
        assert c.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "failed"


def test_network_guard_and_no_dns_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    def sentinel(*args: object, **kwargs: object) -> object:
        raise AssertionError("external request reached DNS")
    monkeypatch.setattr(socket, "getaddrinfo", sentinel)
    with pytest.raises(RuntimeError, match="External network"):
        socket.create_connection(("example.invalid", 443))
