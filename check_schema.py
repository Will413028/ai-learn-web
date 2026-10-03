from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
targets = [root / "backend/openapi.json", root / "frontend/src/lib/generated/api.ts"]
before = [p.read_bytes() for p in targets]
subprocess.run(["make", "-C", str(root), "schema"], check=True)
if before != [p.read_bytes() for p in targets]:
    raise SystemExit("OpenAPI schema/types drift: run make schema and review changes")
print("OpenAPI schema/types match backend")
