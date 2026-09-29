from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    cors_origins: str = "http://localhost:3000"
    database_url: str = "nexus.db"
    # Network binding for the API server. Kept at loopback by default for
    # safety; the demo/launcher script overrides it with 0.0.0.0 so phones
    # on the same LAN can reach the API.
    host: str = "127.0.0.1"
    port: int = 8000
    # Optional write protection for demos. When set, POST/PUT/PATCH
    # endpoints require a matching X-API-Key header (401 otherwise).
    # GETs stay public. Unset -> no enforcement. This is NOT real
    # authentication: never ship this secret to the frontend.
    api_key: str | None = None

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
