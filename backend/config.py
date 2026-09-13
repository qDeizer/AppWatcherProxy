from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 43110
    max_sessions: int = 100_000
    max_memory_bytes: int = 512 * 1024 * 1024
    max_body_bytes: int = 10 * 1024 * 1024
    runtime_dir: Path = PROJECT_ROOT / ".runtime"
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"


settings = Settings()
