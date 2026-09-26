from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SEASCAN_",
        extra="ignore",
    )

    app_name: str = "SeaScan API"
    environment: str = "development"
    api_v1_prefix: str = "/api"
    cors_origins: list[AnyHttpUrl] | list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    database_url: str = "sqlite:///./seascan.db"
    upload_directory: Path = Path("../data/uploads")
    processed_directory: Path = Path("../data/processed")
    model_weights_path: Path | None = None
    max_upload_size_mb: int = Field(default=512, ge=1, le=4096)
    auth_session_hours: int = Field(default=8, ge=1, le=168)
    demo_user_password: str = Field(default="SeaScan@2026", min_length=12)
    bootstrap_admin_password: str | None = Field(default=None, min_length=12)

    @property
    def project_data_directories(self) -> tuple[Path, Path]:
        """Return upload and processed locations resolved relative to this backend directory."""
        backend_directory = Path(__file__).resolve().parents[2]
        return (
            (backend_directory / self.upload_directory).resolve(),
            (backend_directory / self.processed_directory).resolve(),
        )

    @property
    def database_path(self) -> Path:
        """Resolve the SQLite path; non-SQLite URLs are intentionally unsupported in this prototype."""
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("SeaScan Phase 2 supports SQLite database URLs only.")
        raw_path = self.database_url.removeprefix("sqlite:///")
        backend_directory = Path(__file__).resolve().parents[2]
        return (backend_directory / raw_path).resolve()

    @property
    def resolved_model_weights_path(self) -> Path | None:
        if self.model_weights_path is None:
            return None
        backend_directory = Path(__file__).resolve().parents[2]
        return (backend_directory / self.model_weights_path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
