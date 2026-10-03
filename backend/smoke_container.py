"""Opt-in smoke against the local fake Compose demo; creates fixture records."""
import argparse
from time import monotonic, sleep
from uuid import uuid4

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3100")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if base != "http://127.0.0.1:3100":
        parser.error("smoke 僅允許本機 demo，避免誤寫其他環境")
    with httpx.Client(base_url=base + "/api/v1", timeout=30,
                      headers={"Origin": base}) as client:
        def call(method: str, path: str, expected: int = 200, **kwargs: object) -> dict:
            response = client.request(method, path, **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f"{method} {path}: {response.status_code}, expected {expected}")
            return response.json() if response.content else {}

        def wait(path: str, status: str) -> dict:
            deadline = monotonic() + 90
            while monotonic() < deadline:
                result = call("GET", path)
                if result["status"] == status:
                    return result
                if result["status"] == "failed":
                    raise RuntimeError("背景處理失敗")
                sleep(0.5)
            raise RuntimeError("背景處理超時")

        assert call("GET", "/health")["status"] == "ok"
        assert call("GET", "/session")["provider_mode"] == "fake"
        call("POST", "/auth/register", 201, json={"email": f"smoke-{uuid4()}@example.com",
             "password": "test-only-smoke-password-123", "nickname": "Container smoke"})
        doc = call("POST", "/documents", 202,
                   files={"file": ("smoke.txt", b"Python lists and dictionaries")})
        wait(f"/documents/{doc['id']}", "ready")
        job = call("POST", "/quiz/generate", 202,
                   headers={"Idempotency-Key": str(uuid4())},
                   json={"topic": "Python lists", "source_mode": "document",
                         "document_id": doc["id"], "question_count": 3})
        finished = wait(f"/jobs/{job['id']}", "completed")
        quiz = call("GET", f"/quiz/{finished['result_id']}")
        assert not quiz["source"]["degraded"]
        assert len(quiz["questions"]) == 3
        for question in quiz["questions"]:
            assert "correct_answers" not in question
            selected = {"single": ["B"], "multiple": ["A", "B"], "boolean": ["T"]}[question["type"]]
            answer = call("POST", f"/quiz/{quiz['id']}/answers", json={
                "question_id": question["id"], "selected_answers": selected, "duration_ms": 0})
            assert answer["is_correct"]
        report = call("POST", f"/quiz/{quiz['id']}/report", json={})
        assert report["accuracy"] == 100
        assert call("GET", "/user/quizzes")["total"] == 1
        image = call("POST", "/assets", 202,
                     headers={"Idempotency-Key": str(uuid4())},
                     json={"quiz_id": quiz["id"], "prompt": "Python lists"})
        ready = wait(f"/assets/{image['id']}", "completed")
        response = client.get(ready["url"].removeprefix("/api/v1"))
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"
        call("DELETE", f"/assets/{image['id']}", 204, json={})
        call("DELETE", f"/documents/{doc['id']}", 204, json={})
        call("POST", "/auth/logout", 204, json={})
    print("Container smoke passed: auth, RAG, jobs, grading, report, history, private image, deletion")


if __name__ == "__main__":
    main()
