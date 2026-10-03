import httpx
import pytest

import smoke_container


def test_smoke_matches_api_status_and_complete_lifecycle(client, app, monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.Client
    def handler(request: httpx.Request) -> httpx.Response:
        response = client.request(request.method, request.url.path, content=request.content,
                                  headers=dict(request.headers))
        if request.method == "POST" and response.status_code == 202:
            assert app.state.worker.run_once()
        return httpx.Response(response.status_code, content=response.content,
                              headers=dict(response.headers), request=request)
    monkeypatch.setattr(smoke_container.httpx, "Client", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("sys.argv", ["smoke_container.py"])
    smoke_container.main()


def test_smoke_unavailable_backend_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.Client
    monkeypatch.setattr(smoke_container.httpx, "Client", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(502))))
    monkeypatch.setattr("sys.argv", ["smoke_container.py"])
    with pytest.raises(RuntimeError, match="502"):
        smoke_container.main()
