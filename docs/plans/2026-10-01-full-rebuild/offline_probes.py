"""Reproduce selected source behavior using AST-extracted functions and fake dependencies.

No app imports, environment/config reads, database, filesystem writes or network calls.
These probes demonstrate service behavior; they are not the upstream pytest baseline.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

SOURCE = Path(__file__).resolve().parent / "source/backend/app"


def function(relative: str, name: str, namespace: dict):
    path = SOURCE / relative
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


async def probes() -> None:
    score = function("services/scoring_service.py", "compute_score_summary", {})
    record = NS(question_id="q1", selected_answers=["WRONG"], is_correct=True, duration_ms=1)
    assert score([record])["accuracy"] == 100
    print("B01 reproduced: asserted client correctness produces 100% without checking answers")

    read_task = AsyncMock(return_value={"task_id": "foreign", "status": "completed", "result_json": None, "error_message": None})
    get_task = function("services/quiz_service.py", "get_quiz_task_status", {
        "task_repository": NS(get_task=read_task), "QuizTaskStatusResponse": lambda **kw: NS(**kw),
        "QuizGenerateResponse": NS(model_validate=lambda x: x), "QuizGenerationError": RuntimeError})
    result = await get_task("foreign")
    assert result.task_id == "foreign"
    read_task.assert_awaited_once_with("foreign")
    print("B02 reproduced: task status lookup has no caller/owner input")

    leftovers = []
    def partial_write(*args):
        leftovers.append("partial-vector")
        raise RuntimeError("injected partial embedding failure")
    status = AsyncMock()
    rollback = MagicMock()
    process = function("services/knowledge_service.py", "_process_document", {
        "logger": MagicMock(), "document_loader_service": NS(load_and_split=lambda *a: ["chunk"]),
        "vector_store_service": NS(add_document_chunks=partial_write, delete_document_vectors=rollback),
        "knowledge_repository": NS(update_document_status=status)})
    await process("doc", 1, "unused", "txt")
    assert leftovers == ["partial-vector"]
    rollback.assert_not_called()
    assert status.await_args.args == ("doc", "failed")
    print("B03 reproduced: injected partial vector write is not cleaned after processing failure")

    barrier = asyncio.Event()
    lookups = 0
    async def count_used(user_id):
        nonlocal lookups
        lookups += 1
        if lookups == 2:
            barrier.set()
        await barrier.wait()
        return 0
    generate = AsyncMock(return_value="https://example.invalid/fake.png")
    logged = AsyncMock()
    images = function("services/image_service.py", "generate_images_for_quiz", {
        "asyncio": asyncio, "logger": MagicMock(),
        "get_settings": lambda: NS(image_gen_daily_limit=1, image_gen_max_concurrency=1),
        "image_repository": NS(get_today_usage_count=count_used, log_image_generation=logged),
        "generate_image_for_question": generate})
    await asyncio.gather(images([NS(id="q1")], 1, "quiz1"), images([NS(id="q2")], 1, "quiz2"))
    assert generate.await_count == 2 and logged.await_count == 2
    print("B04 reproduced: two concurrent requests generate two images despite daily limit=1")

    output = NS(accuracy=7, mastered_points=[], weak_points=[], three_line_summary=[], advice=[], share_quote="")
    output.model_dump = lambda: {"accuracy": 7}
    report = function("services/report_service.py", "handle_report_generate", {
        "compute_score_summary": score, "generate_report": AsyncMock(return_value=output),
        "logger": MagicMock(), "ReportGenerationError": RuntimeError,
        "ReportGenerateResponse": lambda **kw: NS(**kw)})
    req = NS(quiz_id="q", topic="topic", questions=[], answer_records=[record])
    result = await report(req)
    assert result.accuracy == 7 and score([record])["accuracy"] == 100
    print("B05 reproduced: report accuracy returned from model overrides computed 100% with 7%")


if __name__ == "__main__":
    asyncio.run(probes())
