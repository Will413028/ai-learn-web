"""Opt-in public-fixture eval. Fake self-check is never real quality evidence."""
import argparse
import io
import json
import math
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image

from app.providers import configured_provider
from app.schemas import GeneratedQuiz, GenerateRequest, Plan, ReportNarrative

FIXTURES = [
    ("Python list 與 dictionary", "Python lists preserve order. A dictionary maps unique keys to values."),
    ("PostgreSQL transaction", "Transactions use BEGIN and COMMIT. ROLLBACK discards uncommitted changes."),
    ("HTTP request method", "GET retrieves a representation. POST submits data. DELETE removes a resource."),
]
RAG_DOCS = [text for _, text in FIXTURES] + ["Photosynthesis converts light energy into chemical energy in plants."]
RAG_QUERIES = [("Python dictionary keys", 0), ("PostgreSQL ROLLBACK", 1), ("HTTP DELETE resource", 2), ("plant photosynthesis light", 3)]


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.provider == "cloud" and (not args.allow_external or args.max_requests <= 0):
        raise ValueError("Cloud eval 必須顯式 --allow-external 與正值 --max-requests；服務與費用未選定時不要執行")
    provider = configured_provider(args.provider)
    calls = 0
    timings = []
    results: dict[str, Any] = {"provider": args.provider, "kind": args.kind,
                               "evidence": "fake-harness-only" if args.provider == "fake" else "real-provider",
                               "manual_quality_review": "required"}
    def invoke(method: str, *values: Any) -> Any:
        nonlocal calls
        if calls >= args.max_requests:
            raise ValueError("Eval request 上限已達，不再呼叫 provider")
        calls += 1
        started = monotonic()
        try:
            return getattr(provider, method)(*values, deadline=started + args.timeout)
        finally:
            timings.append(round(monotonic() - started, 3))

    if args.kind in {"quiz", "all"}:
        cases = []
        for topic, context in FIXTURES:
            request = GenerateRequest(topic=topic, question_count=3)
            quiz = GeneratedQuiz.model_validate(invoke("generate", request, context))
            assert len(quiz.questions) == 3
            assert {q.type for q in quiz.questions} == {"single", "multiple", "boolean"}
            cases.append({"topic": topic, "questions": quiz.model_dump()["questions"],
                          "schema_valid": True, "fact_accuracy": "manual-review-required"})
        narrative = ReportNarrative.model_validate(invoke("report", FIXTURES[0][0], []))
        results["quiz"] = cases
        results["report"] = narrative.model_dump()
    if args.kind in {"search", "all"}:
        plan = Plan.model_validate(invoke("plan", "Python official documentation", "", 0))
        sources = invoke("search", "Python official documentation")
        if not sources or any(not all(row.get(key) for key in ("title", "url", "text")) for row in sources):
            raise ValueError("搜尋未取得有效來源")
        extracted = invoke("extract", "https://docs.python.org/3/tutorial/datastructures.html")
        if not extracted:
            raise ValueError("網址未取得內容")
        results["search"] = {"plan": plan.model_dump(), "sources": sources,
                              "extracted": extracted, "relevance": "manual-review-required"}
    if args.kind in {"rag", "all"}:
        vectors = invoke("embed", RAG_DOCS + [q for q, _ in RAG_QUERIES])
        if len(vectors) != len(RAG_DOCS) + len(RAG_QUERIES) or any(
                len(v) != provider.embedding_dimensions or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
                or sum(x*x for x in v) <= 0 for v in vectors):
            raise ValueError("Embedding cardinality/dimension/finite/nonzero 無效")
        def cosine(left: list[float], right: list[float]) -> float:
            return sum(a*b for a, b in zip(left, right, strict=True)) / math.sqrt(sum(x*x for x in left)*sum(x*x for x in right))
        cases = []
        for index, (query, expected) in enumerate(RAG_QUERIES):
            scores = [cosine(vectors[len(RAG_DOCS) + index], doc) for doc in vectors[:len(RAG_DOCS)]]
            chosen = max(range(len(scores)), key=lambda i: scores[i])
            cases.append({"query": query, "expected": expected, "chosen": chosen, "scores": scores})
        recall = sum(case["chosen"] == case["expected"] for case in cases) / len(cases)
        results["rag"] = {"model": provider.embedding_model, "dimensions": provider.embedding_dimensions,
                          "recall_at_1": recall, "cases": cases, "threshold": "requires-calibration"}
        if args.min_recall is not None and recall < args.min_recall:
            raise ValueError("Recall 未達顯式設定門檻")
    if args.kind in {"image", "all"}:
        data = invoke("image", "Educational diagram of Python lists and dictionaries, clear labels")
        with Image.open(io.BytesIO(data)) as picture:
            picture.verify()
            results["image"] = {"format": picture.format, "width": picture.width, "height": picture.height,
                                "bytes": len(data), "legibility_and_relevance": "manual-review-required"}
        image_path = args.output.with_suffix(".png")
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(data)
    results["calls"] = calls
    results["latency_seconds"] = timings
    results["result"] = "harness-pass" if args.provider == "fake" else "transport-schema-pass-manual-review-pending"
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["fake", "cloud"], default="fake")
    parser.add_argument("--kind", choices=["quiz", "search", "rag", "image", "all"], default="all")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--max-requests", type=int, default=9)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--min-recall", type=float)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / ".data/evals/result.json")
    args = parser.parse_args()
    if not 1 <= args.max_requests <= 100 or not 0 < args.timeout <= 300:
        parser.error("request／timeout 上限無效")
    try:
        result = run(args)
    except Exception:
        parser.exit(1, "Eval failed；未通過不能當驗收。檢查設定／額度／服務與測試，不輸出金鑰或原始錯誤內容。\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Eval: {result['result']}, calls={result['calls']}; output={args.output}")


if __name__ == "__main__":
    main()
