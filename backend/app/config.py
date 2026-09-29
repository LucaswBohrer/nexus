from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    cors_origins: str = "http://localhost:3000"
    database_url: str = "nexus.db"

    model_config = {
        "env_prefix": "NEXUS_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def database_path(self) -> Path:
        base_dir = Path(__file__).resolve().parent.parent
        db_url = self.database_url
        path = Path(db_url)
        if path.is_absolute():
            return path
        return base_dir / path


settings = Settings()
