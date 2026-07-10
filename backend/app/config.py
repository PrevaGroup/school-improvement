"""Settings, loaded from .env by pydantic (NOT sourced by the shell).

Connection details are kept as separate fields and assembled with
`sqlalchemy.URL.create`, which escapes them correctly — so passwords may contain
`@ : / $ -` or anything else without breaking a connection string.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- database connection (components, not a URL string) ---
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "sip"

    # App runtime role: sip_app (non-owner, NOBYPASSRLS) — RLS applies to this one.
    app_db_user: str = "sip_app"
    app_db_password: str = ""

    # Migrations role: sip_migrator (owns objects). Used only by Alembic.
    migration_db_user: str = "sip_migrator"
    migration_db_password: str = ""

    # Dev convenience only — accept X-Dev-Tenant instead of a Google token.
    dev_mode: bool = False

    # Prod: expected audience (OAuth client id) for Google ID tokens.
    google_oauth_audience: str | None = None

    def _url(self, user: str, password: str) -> URL:
        # URL.create escapes user/password — no manual percent-encoding needed.
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def database_url(self) -> URL:
        return self._url(self.app_db_user, self.app_db_password)

    @property
    def migration_database_url(self) -> URL:
        return self._url(self.migration_db_user, self.migration_db_password)


settings = Settings()
