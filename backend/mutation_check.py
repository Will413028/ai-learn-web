"""Behavior mutations run in isolated source copies and fresh test databases."""
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv/bin/python"
MUTATIONS = [
    ("exact-scoring", "app/services.py", "is_correct=set(selected) == set(question.correct_answers)",
     "is_correct=bool(set(selected) & set(question.correct_answers))", "tests/test_learning.py::test_exact_scoring"),
    ("quiz-owner", "app/services.py", "where(Quiz.id == quiz_id, Quiz.owner_id == owner)",
     "where(Quiz.id == quiz_id)", "tests/test_learning.py::test_quiz_job_history_owner_isolation"),
    ("csrf", "app/main.py", "if request.headers.get(\"origin\") not in config.origins:",
     "if False:", "tests/test_learning.py::test_csrf_before_side_effects"),
    ("image-reservation", "app/resources.py",
     "if daily >= self.settings.image_daily_limit or active >= self.settings.image_concurrency_limit:",
     "if False:", "tests/test_resources.py::test_image_quota_atomic_and_deletion_keeps_daily_charge"),
    ("image-charge", "app/resources.py", "Asset.charged.is_(True)",
     "Asset.status == \"completed\"", "tests/test_resources.py::test_image_quota_atomic_and_deletion_keeps_daily_charge"),
    ("report-accuracy", "app/services.py", "accuracy=round(correct / len(answers) * 100, 2)",
     "accuracy=100.0", "tests/test_learning.py::test_report_accuracy_calculated_from_answers"),
    ("worker-fence", "app/worker.py",
     'or job.status != "running" or job.version != version or not job.lease_until or job.lease_until <= self.auth.now()',
     "", "tests/test_learning.py::test_job_idempotency_restart_and_fencing"),
]


def run() -> None:
    targets = sorted({row[4] for row in MUTATIONS})
    baseline = subprocess.run([str(PYTHON), "-m", "pytest", "-q", *targets], cwd=ROOT,
                              capture_output=True, text=True, timeout=300)
    (ROOT / "mutation-baseline.log").write_text(baseline.stdout + baseline.stderr)
    if baseline.returncode:
        raise RuntimeError("Mutation baseline failed; inspect backend/mutation-baseline.log")
    for name, filename, before, after, target in MUTATIONS:
        with TemporaryDirectory(prefix=".mutation-", dir=ROOT) as directory:
            copy = Path(directory)
            for folder in ("app", "tests", "migrations"):
                shutil.copytree(ROOT / folder, copy / folder, ignore=shutil.ignore_patterns("__pycache__"))
            for file in ("alembic.ini", "pyproject.toml"):
                shutil.copy2(ROOT / file, copy / file)
            path = copy / filename
            source = path.read_text()
            if before not in source:
                raise RuntimeError(f"Mutation anchor missing: {name}")
            # Worker fencing changes both heartbeat and final commit, preserving the same broken policy.
            path.write_text(source.replace(before, after) if name == "worker-fence" else source.replace(before, after, 1))
            result = subprocess.run([str(PYTHON), "-m", "pytest", "-q", target], cwd=copy,
                                    capture_output=True, text=True, timeout=180)
            output = result.stdout + result.stderr
            (ROOT / f"mutation-{name}.log").write_text(output)
            if result.returncode != 1 or "FAILED " not in output or "ERROR " in output:
                raise RuntimeError(f"Mutation was not caught by an assertion: {name}; inspect its log")
            print(f"caught: {name}", flush=True)


if __name__ == "__main__":
    run()
