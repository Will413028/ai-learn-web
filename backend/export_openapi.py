import json
from pathlib import Path

from app.main import app

target = Path(__file__).resolve().parent / "openapi.json"
target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
