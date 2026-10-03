from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL", "postgresql+psycopg://ai_learn@127.0.0.1:55483/ai_learn"))
    origins: tuple[str, ...] = ("http://127.0.0.1:3100",)
    secure_cookie: bool = False
    provider_mode: str = "fake"
    asset_directory: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / ".data")
    guest_seconds: int = 7 * 86400
    login_seconds: int = 86400
    max_questions: int = 10
    max_documents: int = 10
    max_file_bytes: int = 10 * 1024 * 1024
    rag_min_similarity: float | None = None
    max_chunks: int = 500
    chunk_size: int = 1000
    chunk_overlap: int = 100
    max_search_tools: int = 2
    max_planner_rounds: int = 4
    job_lease_seconds: int = 90
    provider_timeout_seconds: int = 30
    image_daily_limit: int = 3
    image_concurrency_limit: int = 1


def from_environment() -> Settings:
    return Settings(
        origins=tuple(os.getenv("WEB_ORIGINS", "http://127.0.0.1:3100").split(",")),
        rag_min_similarity=float(os.environ["AI_RAG_MIN_SIMILARITY"]) if "AI_RAG_MIN_SIMILARITY" in os.environ else None,
        secure_cookie=os.getenv("SECURE_COOKIE", "false") == "true",
        provider_mode=os.getenv("PROVIDER_MODE", "fake"),
        asset_directory=Path(os.getenv("ASSET_DIRECTORY", str(Path(__file__).resolve().parents[1] / ".data"))),
    )
