"""Settings, loaded from .env by pydantic (NOT sourced by the shell).

DB passwords come from **Google Secret Manager** (runbook Phase 3 — never in the
repo). A direct-password env var is honored as a dev fallback. Connection URLs are
assembled with `sqlalchemy.URL.create`, which escapes any special characters.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- database connection (non-secret parts) ---
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "sip"
    app_db_user: str = "sip_app"            # runtime role (non-owner, NOBYPASSRLS)
    migration_db_user: str = "sip_migrator"  # migrations role (owns objects)

    # --- secrets: primary source is Secret Manager ---
    gcp_project: str | None = None
    app_db_password_secret: str = "sip-app-password"
    migration_db_password_secret: str = "sip-migrator-password"

    # --- dev fallback ONLY: a literal password overrides Secret Manager if set ---
    app_db_password: str | None = None
    migration_db_password: str | None = None

    dev_mode: bool = False
    google_oauth_audience: str | None = None

    def _secret(self, secret_id: str) -> str:
        """Fetch a secret's latest version via Application Default Credentials."""
        from google.cloud import secretmanager

        if not self.gcp_project:
            raise RuntimeError(
                "No password available: set GCP_PROJECT (to read from Secret Manager) "
                "or a dev-fallback password in .env."
            )
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{self.gcp_project}/secrets/{secret_id}/versions/latest"
        return client.access_secret_version(name=name).payload.data.decode("utf-8")

    def _url(self, user: str, password: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=user, password=password,
            host=self.db_host, port=self.db_port, database=self.db_name,
        )

    @property
    def database_url(self) -> URL:
        pw = self.app_db_password or self._secret(self.app_db_password_secret)
        return self._url(self.app_db_user, pw)

    @property
    def migration_database_url(self) -> URL:
        pw = self.migration_db_password or self._secret(self.migration_db_password_secret)
        return self._url(self.migration_db_user, pw)


settings = Settings()
