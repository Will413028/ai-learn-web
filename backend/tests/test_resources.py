from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.db import Asset, Chunk, Database, Document, Job
from app.providers import FakeProvider, ProviderError
from tests.test_learning import generated, register


def upload(client: TestClient, filename: str = "python.txt", data: bytes = b"Python lists and dictionaries") -> dict:
    response = client.post("/api/v1/documents", files={"file": (filename, data)})
    assert response.status_code == 202, response.text
    return response.json()


def test_document_retrieval_and_deletion(client: TestClient, app: FastAPI, database: Database) -> None:
    register(client)
    doc = upload(client)
    assert app.state.worker.run_once()
    ready = client.get(f"/api/v1/documents/{doc['id']}").json()
    assert ready["status"] == "ready" and ready["chunk_count"] == 1
    quiz = generated(client, topic="Python lists", source_mode="document", document_id=doc["id"])
    assert quiz["source"]["degraded"] is False
    assert quiz["source"]["citations"][0]["document_id"] == doc["id"]
    assert client.request("DELETE", f"/api/v1/documents/{doc['id']}", json={}).status_code == 204
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert not app.state.resources.path("documents", doc["id"]).exists()
    assert client.get(f"/api/v1/documents/{doc['id']}").status_code == 404


def test_guest_resources_require_login(client: TestClient) -> None:
    quiz = generated(client)
    assert client.post("/api/v1/documents", files={"file": ("x.txt", b"Python")}).status_code == 401
    assert client.post("/api/v1/assets", json={"quiz_id": quiz["id"], "prompt": "Python"},
                       headers={"Idempotency-Key": str(uuid4())}).status_code == 401


class BrokenEmbedding(FakeProvider):
    def embed(self, texts: list[str], *, deadline: float = float("inf")) -> list[list[float]]:
        return super().embed(texts)[:-1]


def test_failed_embeddings_publish_no_partial_chunks(client: TestClient, app: FastAPI, database: Database) -> None:
    register(client)
    doc = upload(client, data=b"Python " * 400)
    app.state.worker.resources.provider = BrokenEmbedding()
    assert app.state.worker.run_once()
    assert client.get(f"/api/v1/documents/{doc['id']}").json()["status"] == "failed"
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Chunk)) == 0
    app.state.worker.resources.provider = FakeProvider()
    assert client.post(f"/api/v1/documents/{doc['id']}/retry", json={}).status_code == 200
    app.state.worker.run_once()
    assert client.get(f"/api/v1/documents/{doc['id']}").json()["status"] == "ready"


def test_document_failure_never_uses_general_knowledge(client: TestClient, app: FastAPI, database: Database) -> None:
    register(client)
    response = client.post("/api/v1/quiz/generate", json={"topic": "Python", "source_mode": "document",
        "document_id": str(uuid4())}, headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 202
    app.state.worker.run_once()
    job = client.get(f"/api/v1/jobs/{response.json()['id']}").json()
    assert job["status"] == "failed" and not job["result_id"]
    assert "文件" in job["error"]


class BrokenSearch(FakeProvider):
    def search(self, query: str, *, deadline: float = float("inf")) -> list[dict[str, str]]:
        raise ProviderError("搜尋服務不可用")


def test_search_degrades_visibly(client: TestClient, app: FastAPI) -> None:
    app.state.worker.provider = BrokenSearch()
    quiz = generated(client, source_mode="search")
    assert quiz["source"]["degraded"] and quiz["source"]["message"]


def reserve(client: TestClient, quiz_id: str, key: str | None = None):
    return client.post("/api/v1/assets", json={"quiz_id": quiz_id, "prompt": "Python"},
                       headers={"Idempotency-Key": key or str(uuid4())})


def test_image_quota_atomic_and_deletion_keeps_daily_charge(client: TestClient, app: FastAPI, database: Database) -> None:
    register(client)
    quiz = generated(client)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda _: reserve(client, quiz["id"]), range(4)))
    assert sorted(r.status_code for r in responses) == [202, 429, 429, 429]
    successful = next(r.json() for r in responses if r.status_code == 202)
    app.state.worker.run_once()
    content = client.get(f"/api/v1/assets/{successful['id']}/content")
    assert content.status_code == 200 and content.content.startswith(b"\x89PNG")
    assert client.request("DELETE", f"/api/v1/assets/{successful['id']}", json={}).status_code == 204
    assert client.get(f"/api/v1/assets/{successful['id']}/content").status_code == 404
    for _ in range(2):
        response = reserve(client, quiz["id"])
        assert response.status_code == 202
        app.state.worker.run_once()
    assert reserve(client, quiz["id"]).status_code == 429
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Asset).where(Asset.charged.is_(True))) == 3


def test_image_idempotency_and_stale_completion_after_delete(client: TestClient, app: FastAPI) -> None:
    register(client)
    quiz = generated(client)
    key = str(uuid4())
    first = reserve(client, quiz["id"], key).json()
    assert reserve(client, quiz["id"], key).json()["id"] == first["id"]
    claim = app.state.worker.claim()
    assert claim
    job_id, version, owner, kind, payload = claim
    image = app.state.worker.process(kind, owner, payload)
    assert client.request("DELETE", f"/api/v1/assets/{first['id']}", json={}).status_code == 204
    assert app.state.worker.finish(job_id, version, image) is False
    assert not app.state.resources.path("images", first["id"]).exists()


def test_resource_owner_isolation(client: TestClient, app: FastAPI) -> None:
    register(client)
    doc = upload(client)
    quiz = generated(client)
    image = reserve(client, quiz["id"]).json()
    client.post("/api/v1/auth/logout", json={})
    register(client, "other@example.com")
    assert client.get("/api/v1/documents").json() == []
    assert client.get(f"/api/v1/documents/{doc['id']}").status_code == 404
    assert client.request("DELETE", f"/api/v1/documents/{doc['id']}", json={}).status_code == 404
    assert client.get(f"/api/v1/assets/{image['id']}").status_code == 404


def test_document_quota_creates_no_extra_record(client: TestClient, app: FastAPI, database: Database) -> None:
    register(client)
    app.state.resources.settings = replace(app.state.resources.settings, max_documents=1)
    upload(client)
    assert client.post("/api/v1/documents", files={"file": ("other.txt", b"Python")}).status_code == 409
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_retrieval_is_limited_to_selected_document(client: TestClient, app: FastAPI) -> None:
    register(client)
    first = upload(client, "first.txt", b"Python lists")
    second = upload(client, "second.txt", b"Python tuples")
    app.state.worker.run_once()
    app.state.worker.run_once()
    quiz = generated(client, topic="Python", source_mode="document", document_id=first["id"])
    assert {citation["document_id"] for citation in quiz["source"]["citations"]} == {first["id"]}
    assert second["id"] != first["id"]


def test_image_transfer_failure_releases_reservation_and_worker_continues(client: TestClient, app: FastAPI,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    register(client)
    quiz = generated(client)
    image = reserve(client, quiz["id"]).json()
    original = Path.write_bytes

    def fail_staging(path: Path, data: bytes) -> int:
        if path.name.endswith(".staging"):
            raise OSError("test-only storage failure")
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_staging)
    assert app.state.worker.run_once()
    failed = client.get(f"/api/v1/assets/{image['id']}").json()
    assert failed["status"] == "failed" and failed["error"] and not failed["url"]
    assert reserve(client, quiz["id"]).status_code == 202
    monkeypatch.setattr(Path, "write_bytes", original)
    assert app.state.worker.run_once()
    assert generated(client)["questions"]


def test_auto_image_is_reserved_before_quiz_completion_is_visible(client: TestClient, app: FastAPI) -> None:
    register(client)
    first = generated(client, include_images=True)
    assert len(first["image_ids"]) == 1
    assert client.get(f"/api/v1/assets/{first['image_ids'][0]}").json()["status"] == "pending"
    # The active image consumes the only concurrency slot, without preventing another quiz.
    second_job = client.post("/api/v1/quiz/generate", json={"topic": "Python", "include_images": True},
                             headers={"Idempotency-Key": str(uuid4())}).json()
    image_claim = app.state.worker.claim()
    quiz_claim = app.state.worker.claim()
    assert image_claim and quiz_claim and quiz_claim[3] == "quiz"
    job_id, version, owner, kind, payload = quiz_claim
    result = app.state.worker.process(kind, owner, payload)
    assert app.state.worker.finish(job_id, version, result)
    status = client.get(f"/api/v1/jobs/{second_job['id']}").json()
    assert status["status"] == "completed"
    quiz = client.get(f"/api/v1/quiz/{status['result_id']}").json()
    assert quiz["source"]["image_message"] and not quiz["image_ids"]


@pytest.mark.parametrize("filename,data", [("bad.pdf", b"bad"), ("bad.docx", b"bad"), ("bad.txt", b"\xff")])
def test_invalid_documents_fail_without_chunks(client: TestClient, app: FastAPI, database: Database,
                                              filename: str, data: bytes) -> None:
    register(client)
    doc = upload(client, filename, data)
    app.state.worker.run_once()
    assert client.get(f"/api/v1/documents/{doc['id']}").json()["status"] == "failed"
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Chunk)) == 0
        job = session.scalar(select(Job).where(Job.kind == "document"))
        assert job and job.status == "failed"
