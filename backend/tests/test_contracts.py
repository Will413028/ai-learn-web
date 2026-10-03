from time import monotonic, sleep

import pytest

from app.providers import ProviderError, configured_provider
from app.services import bounded_call
from app.worker import validate_url


def test_provider_receives_monotonic_deadline() -> None:
    start = monotonic()
    observed: list[float] = []

    def provider(deadline: float) -> str:
        observed.append(deadline)
        return "done"

    assert bounded_call(provider, 2) == "done"
    assert start + 2 <= observed[0] <= monotonic() + 2


def test_expired_output_is_rejected() -> None:
    def provider(deadline: float) -> str:
        sleep(max(0, deadline - monotonic()) + 0.01)
        return "late output"

    with pytest.raises(ProviderError, match="逾時"):
        bounded_call(provider, 0.01)


def test_provider_error_sanitization() -> None:
    def provider(deadline: float) -> str:
        raise ValueError("private body and credentials must never reach errors")

    with pytest.raises(ProviderError) as error:
        bounded_call(provider, 1)
    assert "private" not in str(error.value) and "credentials" not in str(error.value)


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://169.254.169.254", "http://[::1]",
    "http://localhost", "http://host.internal", "file:///etc/passwd", "http://user:pass@example.com"])
def test_private_urls_rejected(url: str) -> None:
    with pytest.raises(ProviderError):
        validate_url(url)


def test_public_url_allowed() -> None:
    validate_url("https://example.com/article")


def test_unknown_provider_mode_never_silently_uses_fake() -> None:
    with pytest.raises(RuntimeError):
        configured_provider("unconfigured-real-provider")
