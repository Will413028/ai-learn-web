import asyncio
import base64
from dataclasses import replace
import json
from time import monotonic

import httpx
import pytest

from app.cloud_provider import CloudConfig, CloudProvider, strict_schema
from app.providers import FakeProvider, ProviderError, configured_provider
from app.schemas import GenerateRequest, Plan


CONFIG = CloudConfig("https://ai.example.com/v1", "text-fixture", "embed-fixture", 2,
                     "image-fixture", "test-only-token", search_key="test-only-search-token")


def provider(handler: object) -> CloudProvider:
    return CloudProvider(CONFIG, httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_cloud_generate_contract_no_retry() -> None:
    calls = []
    request = GenerateRequest(topic="Python")
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        payload = json.loads(req.content)
        assert payload["model"] == CONFIG.text_model
        assert payload["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(FakeProvider().generate(request, ""))}}]})
    result = provider(handler).generate(request, "", deadline=monotonic() + 2)
    assert len(result["questions"]) == 3  # type: ignore[index]
    assert len(calls) == 1


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_cloud_error_sanitized_single_attempt(status: int) -> None:
    calls = []
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(status, json={"private": "private-request-and-token"})
    with pytest.raises(ProviderError) as error:
        provider(handler).generate(GenerateRequest(topic="Private topic"), "", deadline=monotonic() + 2)
    assert "private-request" not in str(error.value) and "test-only-token" not in str(error.value)
    assert len(calls) == 1


def test_total_timeout_cancels_transport() -> None:
    stopped = []
    async def handler(req: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(10)
            return httpx.Response(200, json={})
        finally:
            stopped.append(True)
    started = monotonic()
    with pytest.raises(ProviderError, match="逾時"):
        asyncio.run(provider(handler)._post(CONFIG.base_url, "/chat/completions", {}, CONFIG.api_key, started + 2))
    assert stopped == [True] and monotonic() - started < 5


def test_expired_deadline_sends_nothing() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        pytest.fail("deadline 已過仍呼叫 transport")
    with pytest.raises(ProviderError, match="逾時"):
        provider(handler).embed(["Python"], deadline=monotonic() - 1)


def test_embeddings_restore_input_order() -> None:
    result = provider(lambda _: httpx.Response(200, json={"data": [
        {"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]})).embed(["one", "two"])
    assert result == [[1.0, 0.0], [0.0, 1.0]]


def test_embedding_duplicate_index_rejected() -> None:
    with pytest.raises(ProviderError):
        provider(lambda _: httpx.Response(200, json={"data": [
            {"index": 0, "embedding": [1.0, 0.0]}, {"index": 0, "embedding": [0.0, 1.0]}]})).embed(["one", "two"])


def test_image_base64_only() -> None:
    data = FakeProvider().image("Python")
    assert provider(lambda _: httpx.Response(200, json={"data": [{
        "b64_json": base64.b64encode(data).decode()}]})).image("Python") == data
    with pytest.raises(ProviderError):
        provider(lambda _: httpx.Response(200, json={"data": [{"url": "https://unknown.example.com/image"}]})).image("Python")


def test_report_wire_mastery_converted() -> None:
    data = {"summary": "Summary", "mastery": [{"knowledge_point": "Python", "level": "review"}],
            "weaknesses": ["Python"], "suggestions": ["Practice"], "share_quote": "Keep learning"}
    p = provider(lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                 "message": {"content": json.dumps(data)}}]}))
    result = p.report("Python", [])
    assert result["mastery"] == {"Python": "review"}  # type: ignore[index]


def test_search_contract_and_empty_extract_config() -> None:
    p = provider(lambda _: httpx.Response(200, json={"results": [{"title": "Python", "url": "https://docs.python.org/3/",
                 "content": "Official Python documentation"}]}))
    assert p.search("Python")[0]["text"] == "Official Python documentation"
    p.config = replace(CONFIG, search_key="")
    with pytest.raises(ProviderError, match="尚未設定"):
        p.search("Python")


def test_private_extract_never_sent() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        pytest.fail("private extract 已送出")
    with pytest.raises(ProviderError):
        provider(handler).extract("http://127.0.0.1/private")


def test_cloud_no_implicit_model_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AI_API_BASE_URL", "AI_TEXT_MODEL", "AI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="不會降級"):
        configured_provider("cloud")
    assert "test-only-token" not in repr(CONFIG)


def test_strict_schema_defaults_become_required() -> None:
    schema = strict_schema(Plan.model_json_schema())
    assert schema["required"] == ["action", "query"]
    assert "default" not in schema["properties"]["query"]


def test_sync_extract_deadline_terminates_blocking_dns(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import os
    import sys
    marker = tmp_path / "resolver-pid"
    script = ("import os,socket,sys,time; from pathlib import Path; "
              "sys.stdin.read(); Path(sys.argv[1]).write_text(str(os.getpid())); "
              "socket.getaddrinfo=lambda *a,**k: time.sleep(30); socket.getaddrinfo('fixture.invalid',443)")
    p = provider(lambda _: pytest.fail("timeout 後仍發 extract"))
    monkeypatch.setattr(p, "_transport_command", lambda: [sys.executable, "-c", script, str(marker)])
    started = monotonic()
    with pytest.raises(ProviderError, match="逾時"):
        p.extract("https://public.example.com/article", deadline=started + 2)
    assert marker.exists() and monotonic() - started < 5
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_image_response_format_capability() -> None:
    data = FakeProvider().image("Python")
    payloads = []
    def handler(req: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(req.content))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(data).decode()}]})
    p = provider(handler)
    p.image("Python")
    p.config = replace(CONFIG, image_response_format="b64_json")
    p.image("Python")
    assert "response_format" not in payloads[0]
    assert payloads[1]["response_format"] == "b64_json"


def test_embedding_identity_includes_endpoint_model_dimension() -> None:
    p = CloudProvider(CONFIG)
    other = CloudProvider(replace(CONFIG, base_url="https://other.example.com/v1"))
    dimensions = CloudProvider(replace(CONFIG, embedding_dimensions=3))
    assert len({p.embedding_model, other.embedding_model, dimensions.embedding_model}) == 3


@pytest.mark.parametrize("operation", ["http", "resolve"])
def test_network_guard_reaches_real_transport_child(operation: str) -> None:
    p = CloudProvider(CONFIG)
    with pytest.raises(ProviderError, match="測試禁止外部"):
        if operation == "http":
            p.embed(["offline sentinel"], deadline=monotonic() + 10)
        else:
            p.extract("https://public.example.com/article", deadline=monotonic() + 10)


def test_timeout_drains_child_stdout_and_reaps(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import os
    import sys
    marker = tmp_path / "pipe-pid"
    script = ("import os,sys,time; from pathlib import Path; sys.stdin.read(); "
              "Path(sys.argv[1]).write_text(str(os.getpid())); "
              "sys.stdout.buffer.write(b'x'*2**20); sys.stdout.buffer.flush(); time.sleep(30)")
    p = CloudProvider(CONFIG)
    monkeypatch.setattr(p, "_transport_command", lambda: [sys.executable, "-c", script, str(marker)])
    started = monotonic()
    with pytest.raises(ProviderError, match="逾時"):
        p.embed(["fixture"], deadline=started + 2)
    assert marker.exists() and monotonic() - started < 5
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
