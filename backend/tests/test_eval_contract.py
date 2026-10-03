from argparse import Namespace
from pathlib import Path

import pytest

import eval_provider


def args(tmp_path: Path, **values: object) -> Namespace:
    return Namespace(**{"provider": "fake", "kind": "all", "allow_external": False,
                       "max_requests": 9, "timeout": 30, "min_recall": None,
                       "output": tmp_path / "eval.json", **values})


def test_eval_fake_does_not_claim_real_quality(tmp_path: Path) -> None:
    result = eval_provider.run(args(tmp_path))
    assert result["evidence"] == "fake-harness-only"
    assert result["result"] == "harness-pass" and result["calls"] == 9
    assert result["manual_quality_review"] == "required"
    assert (tmp_path / "eval.png").exists()


def test_cloud_eval_gate_before_reading_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_provider, "configured_provider", lambda _: pytest.fail("未 opt-in 讀 cloud config"))
    with pytest.raises(ValueError, match="顯式"):
        eval_provider.run(args(tmp_path, provider="cloud"))


def test_eval_request_budget_stops_before_next_call(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="上限"):
        eval_provider.run(args(tmp_path, max_requests=1))


def test_bad_recall_fails_explicit_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Collapsed(eval_provider.configured_provider("fake").__class__):
        def embed(self, texts, *, deadline=float("inf")):
            return [[1.0] + [0.0] * (self.embedding_dimensions - 1) for _ in texts]
    monkeypatch.setattr(eval_provider, "configured_provider", lambda _: Collapsed())
    with pytest.raises(ValueError, match="Recall"):
        eval_provider.run(args(tmp_path, kind="rag", min_recall=0.9))
