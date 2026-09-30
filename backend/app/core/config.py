# config.py - typed application settings loaded from environment variables
from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    domain: str = ":80"
    base_url: str = "http://localhost"
    secret_key: str = "dev-secret-key-change-me"

    postgres_db: str = "spseiostrava"
    postgres_user: str = "spseiostrava"
    postgres_password: str = "spseiostrava"
    database_url: str = "postgresql+psycopg://spseiostrava:spseiostrava@db:5432/spseiostrava"

    allowed_email_domain: str = "spseiostrava.cz"
    admin_emails: str = ""

    contact_email: str = "contact@example.cz"

    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.cz"

    upload_dir: str = "/data/uploads"
    max_image_mb: int = 8
    max_resource_mb: int = 25

    auto_hide_report_threshold: int = 3
    quotes_require_approval: bool = True

    @cached_property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


settings = Settings()