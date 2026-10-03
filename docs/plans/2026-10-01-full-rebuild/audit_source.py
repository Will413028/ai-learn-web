"""Offline inventory gate. Reads selected tracked code; never imports the application."""
from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source"
SNAPSHOT = HERE / "source-inventory.json"
PIN = "d68cf0b77dd89cae1143abe8c300b239da79a6ea"


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(SOURCE), *args], text=True).strip()


def location(path: Path, line: int) -> str:
    return f"{path.relative_to(SOURCE)}:{line}"


def collect() -> dict:
    assert git("rev-parse", "HEAD") == PIN, "Source revision changed"
    assert not git("status", "--porcelain"), "Source checkout must remain clean"
    tracked = git("ls-files", "-z").split("\0")
    tracked = [p for p in tracked if p]
    result = {"commit": PIN, "tracked_file_count": len(tracked), "routes": [],
              "models": [], "tables": [], "prompts": [], "tests": [],
              "frontend_api": [], "pages": [], "spec_requirements": []}
    for path in sorted((SOURCE / "backend/app/api/v1/routes").glob("*.py")):
        tree = ast.parse(path.read_text())
        prefix = ""
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                for kw in node.value.keywords:
                    if kw.arg == "prefix":
                        prefix = ast.literal_eval(kw.value)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                method = dec.func.attr
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                route = prefix + ast.literal_eval(dec.args[0])
                step = 2 if route == "/health" else 6 if route.startswith("/knowledge") else 4 if route.startswith("/user") else 3
                if route == "/quiz/generate/async" or route.startswith("/quiz/task/"):
                    step = 5
                disposition = "replace-auth" if route == "/user/login" else "rewrite"
                result["routes"].append({"method": method.upper(), "path": "/api/v1" + route,
                    "function": node.name, "source": location(path, dec.lineno),
                    "parameters": [a.arg for a in node.args.args], "step": step, "disposition": disposition})
    for path in sorted((SOURCE / "backend/app/models").glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                fields = [n.target.id for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
                result["models"].append({"name": node.name, "fields": fields,
                    "source": location(path, node.lineno), "disposition": "redesign-contract"})
    path = SOURCE / "backend/app/core/db.py"
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", node.value)
            if match:
                result["tables"].append({"name": match[1], "source": location(path, node.lineno),
                    "disposition": "redesign-postgresql"})
    for path in sorted((SOURCE / "backend/app/prompts").glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        result["prompts"].append({"name": target.id, "source": location(path, node.lineno),
                            "disposition": "rewrite-contract-and-grounding"})
    for path in sorted((SOURCE / "backend/tests").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                result["tests"].append({"name": node.name, "source": location(path, node.lineno),
                    "disposition": "port-behavior-review-old-contract"})
    path = SOURCE / "frontend/src/services/api.ts"
    text = path.read_text()
    pages = sorted((SOURCE / "frontend/src/pages").glob("*/index.tsx")) + [SOURCE / "frontend/src/app.ts"]
    consumers = sorted(p for p in (SOURCE / "frontend/src").rglob("*") if p.suffix in {".ts", ".tsx"})
    for match in re.finditer(r"^export (?:async )?function (\w+)", text, re.M):
        name = match[1]
        hits = []
        for consumer in consumers:
            for line, value in enumerate(consumer.read_text().splitlines(), 1):
                is_declaration = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(", value)
                if not is_declaration and re.search(r"\b" + re.escape(name) + r"\s*\(", value):
                    hits.append(location(consumer, line))
        result["frontend_api"].append({"name": name, "source": location(path, text[:match.start()].count("\n") + 1),
            "consumers": hits, "disposition": "replace-nextjs-client"})
    for path in pages:
        result["pages"].append({"source": str(path.relative_to(SOURCE)),
            "disposition": "rewrite-web" if "pages" in path.parts else "replace-wechat-bootstrap"})
    for path in sorted((SOURCE / "openspec/specs").glob("*/spec.md")):
        for line, value in enumerate(path.read_text().splitlines(), 1):
            if value.startswith("### Requirement:"):
                result["spec_requirements"].append({"name": value.removeprefix("### Requirement: "),
                    "source": location(path, line), "disposition": "review-D5-D7-source-contract"})
    return result


def validate(data: dict) -> None:
    assert data["commit"] == PIN
    for category in ("routes", "models", "tables", "prompts", "tests", "frontend_api", "pages", "spec_requirements"):
        assert data[category], f"Empty category: {category}"
        for row in data[category]:
            assert row.get("disposition"), f"Missing disposition: {row}"
            path = row["source"].split(":")[0]
            assert (SOURCE / path).is_file(), path
    assert len({(r["method"], r["path"]) for r in data["routes"]}) == len(data["routes"])


def check_snapshot(saved: dict, actual: dict) -> None:
    validate(saved)
    assert saved == actual, "Inventory drift; review before --update"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    actual = collect()
    validate(actual)
    if args.update:
        SNAPSHOT.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n")
    else:
        check_snapshot(json.loads(SNAPSHOT.read_text()), actual)
    if args.self_test:
        broken = copy.deepcopy(actual)
        broken["routes"][0]["disposition"] = ""
        try:
            validate(broken)
        except AssertionError:
            print("Mutation rejected: missing route disposition")
        else:
            raise AssertionError("Mutation unexpectedly passed")
        broken = copy.deepcopy(actual)
        broken["models"].pop()
        try:
            check_snapshot(broken, actual)
        except AssertionError:
            print("Mutation rejected: missing model differs from source inventory")
        else:
            raise AssertionError("Missing model mutation unexpectedly passed")
    print(json.dumps({"commit": PIN, **{k: len(v) for k, v in actual.items() if isinstance(v, list)}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
