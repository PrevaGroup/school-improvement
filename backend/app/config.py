"""Settings, loaded from .env by pydantic (NOT sourced by the shell).

DB passwords come from **Google Secret Manager** (runbook Phase 3 — never in the
repo). A direct-password env var is honored as a dev fallback. Connection URLs are
assembled with `sqlalchemy.URL.create`, which escapes any special characters.
"""
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy import URL

# Resolved secrets are cached per-process: without this, each Secret Manager fetch
# is a fresh ADC/metadata call, and a long batch that re-resolves the key per item
# (e.g. the SIP extractor's per-PDF Anthropic client) gets N chances to hit a
# transient metadata failure — one of which killed a run. Fetch each secret once.
_SECRET_CACHE: dict[str, str] = {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- database connection (non-secret parts) ---
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "sip"
    app_db_user: str = "sip_app"            # runtime role (non-owner, NOBYPASSRLS)
    migration_db_user: str = "sip_migrator"  # migrations role (owns objects)

    # --- Cloud SQL Python Connector (Cloud Run): set to activate, else Auth-Proxy URL ---
    # e.g. "school-improvement-501916:us-central1:school-improvement-sql"
    instance_connection_name: str | None = None
    db_ip_type: str = "public"              # "public" or "private" (VPC)

    # --- secrets: primary source is Secret Manager ---
    gcp_project: str | None = None
    app_db_password_secret: str = "sip-app-password"
    migration_db_password_secret: str = "sip-migrator-password"

    # --- dev fallback ONLY: a literal password overrides Secret Manager if set ---
    app_db_password: str | None = None
    migration_db_password: str | None = None

    # --- Anthropic API key for the SIP extractor (etl/ca/sip) ---
    # Prod: Secret Manager `anthropic-api-key`. Dev fallback: the standard
    # ANTHROPIC_API_KEY env var (pydantic maps the field name to it).
    anthropic_api_key: str | None = None
    anthropic_api_key_secret: str = "anthropic-api-key"
    # Chat-mart model. Haiku for cost (Claude spend is gated per the deploy); switch to
    # claude-opus-4-8 for more depth. NB: Haiku 4.5 has no thinking/effort support.
    chat_model: str = "claude-haiku-4-5"

    dev_mode: bool = False
    # Identity Platform/Firebase ID-token audience. Defaults to gcp_project (the token's `aud`);
    # set explicitly only to override.
    google_oauth_audience: str | None = None
    # How a verified identity becomes a tenant (see app/security.py):
    #   1) a custom claim on the user (recommended) — this claim name, or
    #   2) fallback: map the email domain, e.g. {"lbschools.net": "lbusd"}.
    tenant_claim: str = "tenant_id"
    domain_tenant_map: dict[str, str] = {}

    # --- who may sign in at all (see app/security.py) ---
    # Email domains allowed through the door, e.g. "prevagroup.com,gatesfoundation.org".
    # Authentication is not invitation: with a Google provider enabled, ANY Gmail account can
    # obtain a valid token, so this is what turns "signed in" into "invited". Expected to stay
    # a short list.
    #
    # FAILS CLOSED: empty means nobody. An unset allowlist must not silently mean "everyone" —
    # that is precisely the hole this closes, and a deploy that forgets it should lock people
    # out (loud, fixable) rather than let the internet at the Anthropic balance (silent, not).
    # `NoDecode` is required, not decorative: without it pydantic-settings tries json.loads()
    # on the env value BEFORE any validator runs, so a plain "a.com,b.org" raises SettingsError
    # at import and the app never starts. NoDecode hands the raw string to the validator below.
    allowed_email_domains: Annotated[set[str], NoDecode] = set()

    @field_validator("allowed_email_domains", mode="before")
    @classmethod
    def _split_domains(cls, v):
        """Accept "a.com, b.org" as well as JSON or a real list.

        Plain comma-separated is the point: a JSON list in `gcloud run deploy --set-env-vars`
        collides with gcloud's own comma-as-delimiter parsing (see backend/DEPLOY.md). Lowercased
        here so the comparison in security.py can't be case-tricked.
        """
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):                      # tolerate JSON if someone writes it
                import json
                return {str(d).strip().lower() for d in json.loads(s) if str(d).strip()}
            return {d.strip().lower() for d in s.split(",") if d.strip()}
        if isinstance(v, (list, set, tuple)):
            return {str(d).strip().lower() for d in v if str(d).strip()}
        return v

    @property
    def identity_platform_audience(self) -> str | None:
        return self.google_oauth_audience or self.gcp_project

    def _secret(self, secret_id: str) -> str:
        """Fetch a secret's latest version via ADC. Cached per-process (see _SECRET_CACHE)."""
        if secret_id in _SECRET_CACHE:
            return _SECRET_CACHE[secret_id]
        from google.cloud import secretmanager

        if not self.gcp_project:
            raise RuntimeError(
                "No password available: set GCP_PROJECT (to read from Secret Manager) "
                "or a dev-fallback password in .env."
            )
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{self.gcp_project}/secrets/{secret_id}/versions/latest"
        value = client.access_secret_version(name=name).payload.data.decode("utf-8")
        _SECRET_CACHE[secret_id] = value
        return value

    def _url(self, user: str, password: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=user, password=password,
            host=self.db_host, port=self.db_port, database=self.db_name,
        )

    @property
    def app_db_password_value(self) -> str:
        return self.app_db_password or self._secret(self.app_db_password_secret)

    @property
    def database_url(self) -> URL:
        return self._url(self.app_db_user, self.app_db_password_value)

    @property
    def migration_database_url(self) -> URL:
        pw = self.migration_db_password or self._secret(self.migration_db_password_secret)
        return self._url(self.migration_db_user, pw)

    @property
    def anthropic_api_key_value(self) -> str:
        return self.anthropic_api_key or self._secret(self.anthropic_api_key_secret)


settings = Settings()
