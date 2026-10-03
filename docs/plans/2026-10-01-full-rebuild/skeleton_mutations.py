"""Destructive checks run only on disposable copies inside this attachment directory."""
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PYTHON = ROOT / "backend/.venv/bin/python"


def mutate(path: Path, before: str, after: str) -> None:
    text = path.read_text()
    if text.count(before) != 1:
        raise AssertionError(f"Mutation anchor drift: {path.name}")
    path.write_text(text.replace(before, after))


def rejected(name: str, command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=60)
    if result.returncode == 0:
        raise AssertionError(f"Mutation survived: {name}")
    output = result.stdout + result.stderr
    # A missing executable/import is infrastructure failure, not an effective mutation.
    if "FAILED" not in output and "AssertionError" not in output:
        raise AssertionError(f"Mutation did not reach an assertion: {name}\n{output[-2000:]}")
    print(f"Mutation rejected: {name}")


def main() -> None:
    cases = [
        ("provider-schema", "app/main.py",
         "question = InternalQuestion.model_validate(adapter.generate(body.topic))",
         "question = InternalQuestion.model_construct(**adapter.generate(body.topic))",
         "test_provider_answer_must_reference_an_option"),
        ("network-guard", "app/network_guard.py",
         'raise RuntimeError("External network is blocked in fake tests")', "return",
         "test_external_network_blocked_before_connect"),
        ("csrf", "app/main.py", 'if request.headers.get("origin") not in origins:', "if False:",
         "test_csrf_rejected"),
        ("answer-secrecy", "app/main.py", "class PublicQuestion(Schema):",
         'class PublicQuestion(Schema):\n    correct_answer: str = "B"',
         "test_answers_private_until_submit"),
    ]
    for name, filename, before, after, test in cases:
        with tempfile.TemporaryDirectory(prefix="skeleton-mutation-", dir=HERE) as directory:
            copy = Path(directory)
            for subdir in ("app", "tests"):
                shutil.copytree(ROOT / "backend" / subdir, copy / subdir,
                                ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy2(ROOT / "backend/pyproject.toml", copy / "pyproject.toml")
            mutate(copy / filename, before, after)
            rejected(name, [str(PYTHON), "-m", "pytest", "-q", "-k", test], copy)
    with tempfile.TemporaryDirectory(prefix="skeleton-mutation-", dir=HERE) as directory:
        config = Path(directory) / "next.config.ts"
        shutil.copy2(ROOT / "frontend/next.config.ts", config)
        mutate(config, "127.0.0.1:8100", "127.0.0.1:8101")
        rejected("proxy-destination", ["node", str(ROOT / "frontend/test-support/proxy.test.mjs"),
                                      str(config)], ROOT)
    with tempfile.TemporaryDirectory(prefix="skeleton-mutation-", dir=HERE) as directory:
        guard = Path(directory) / "browser-network.mjs"
        shutil.copy2(ROOT / "frontend/test-support/browser-network.mjs", guard)
        mutate(guard, 'if (url.origin !== "http://127.0.0.1:3100")', "if (false)")
        rejected("browser-network-guard", ["node", str(ROOT / "frontend/test-support/browser-network.test.mjs"),
                                          str(guard)], ROOT)
    print("6 skeleton mutations rejected; no external requests sent")


if __name__ == "__main__":
    main()
