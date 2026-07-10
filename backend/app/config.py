from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Runtime connection: the sip_app role (non-owner, NOBYPASSRLS) — RLS applies here.
    database_url: str = "postgresql+psycopg://sip_app:@127.0.0.1:5432/sip"

    # Only used by Alembic (migrations/env.py): the sip_migrator role.
    migration_database_url: str | None = None

    # Dev convenience only — accept X-Dev-Tenant instead of a Google token.
    dev_mode: bool = False

    # Prod: expected audience (OAuth client id) for Google ID tokens.
    google_oauth_audience: str | None = None


settings = Settings()
