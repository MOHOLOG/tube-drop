from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    base_dir: Path = BASE_DIR
    storage_dir: Path = BASE_DIR / "storage"
    media_dir: Path = BASE_DIR / "storage" / "media"
    covers_dir: Path = BASE_DIR / "storage" / "covers"
    db_path: Path = BASE_DIR / "storage" / "app.db"

    host: str = "0.0.0.0"
    port: int = 8000
    host_ip: str | None = None

    @computed_field
    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)

    def model_post_init(self, __context: object, /) -> None:
        self.ensure_directories()


settings = Settings()
