"""Central configuration: every setting is read from .env in one place."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _split_hosts(raw: str) -> list[str]:
    return [h.strip() for h in raw.split(",") if h.strip()]


@dataclass(frozen=True)
class Settings:
    # Model
    model_provider: str = os.getenv("MODEL_PROVIDER", "groq")
    model_name: str = os.getenv("MODEL_NAME", "openai/gpt-oss-120b")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

    # Runner
    allowed_hosts: list[str] = field(
        default_factory=lambda: _split_hosts(os.getenv("ALLOWED_HOSTS", ""))
    )
    runner_timeout: int = int(os.getenv("RUNNER_TIMEOUT", "60"))
    headless: bool = os.getenv("HEADLESS", "false").lower() == "true"

    # Storage
    data_dir: Path = PROJECT_ROOT / os.getenv("DATA_DIR", "data")
    db_path: Path = PROJECT_ROOT / os.getenv("DB_PATH", "data/app.db")


settings = Settings()
