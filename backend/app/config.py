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
    # --- session freshness: how long a sign-in lasts (see app/security.py) ---
    # Days since the token's `auth_time` (the actual sign-in moment — it rides through the
    # SDK's hourly ID-token refreshes unchanged) before the backend 401s and the SPA routes
    # back to sign-in. This is the only offboarding bound the app itself controls: refresh
    # tokens otherwise live forever, so a departed employee's persisted session would too.
    session_max_age_days: float = 7.0
    # How a verified identity becomes a tenant (see app/security.py):
    #   1) a custom claim on the user (recommended) — this claim name, or
    #   2) fallback: map the email domain, e.g. {"lbschools.net": "lbusd"}.
    tenant_claim: str = "tenant_id"
    domain_tenant_map: dict[str, str] = {}

    # --- chat trace emission (app/traces.py — docs/design/eval-trace-system.md phase 1) ---
    # Unset = tracing disabled entirely (the dev default). When set, each /api/chat turn
    # writes one JSONL object to gs://<bucket>/traces/v1/ from a background task. The write
    # is fire-and-forget by decision (§8.1): no retries, a lost trace only logs a warning.
    # The bucket's 90-day lifecycle rule is set at bucket creation, not here.
    traces_bucket: str | None = None
    # Salt for principal_hash in traces (identity is hashed, never stored raw). Prod: Secret
    # Manager; a literal dev fallback overrides it, same pattern as the DB passwords.
    trace_salt: str | None = None
    trace_salt_secret: str = "trace-principal-salt"
    # Stamped by the deploy (--set-env-vars GIT_SHA=$(git rev-parse HEAD)) so a trace can
    # attribute a behavior delta to a code change. Falls back to K_REVISION in traces.py.
    git_sha: str | None = None

    # --- Claude spend caps for /api/chat (app/usage.py) ---
    # Dollars/day, derived from raw token counts x MODEL_PRICES. Per-user bounds one runaway
    # account; global bounds (cap x allowlisted users) — the real exposure once the IAM gate
    # opens. The chat loop's own ceilings bound each message well under $1, so $2/day is
    # ~10-40 heavy messages: invisible to a tester, a wall to a script.
    chat_daily_user_usd: float = 2.00
    chat_daily_global_usd: float = 20.00

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

    # --- who may sign in AND HOW: domain -> required sign-in provider ---
    # e.g. "prevagroup.com=google.com,gatesfoundation.org=microsoft.com" (JSON dict also
    # accepted). One table, three jobs — invitation (keys), routing (the frontend mirrors
    # this map for its email-first screen), and ENFORCEMENT: security.py rejects a token
    # whose sign_in_provider doesn't match the domain's entry. The enforcement is the
    # Security-101 constraint: access must ride an identity the employer can revoke, so a
    # personal Google account on a gates address must be structurally impossible, not just
    # unlinked. Supersedes ALLOWED_EMAIL_DOMAINS (kept as a fallback that maps every domain
    # to google.com — true for the preva-only era, so old deploys keep working).
    allowed_domain_providers: Annotated[dict[str, str], NoDecode] = {}

    @field_validator("allowed_domain_providers", mode="before")
    @classmethod
    def _split_domain_providers(cls, v):
        """Accept "a.com=google.com, b.org=microsoft.com" or a JSON dict.

        Same NoDecode dance as the allowlist below (see that comment). A malformed pair
        raises — a typo'd map should fail the deploy loudly, not half-open the door.
        Lowercased on both sides: domains for the same reason as the allowlist; provider
        ids because Identity Platform's are lowercase constants ("google.com").
        """
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return {}
            if s.startswith("{"):
                import json
                return {str(k).strip().lower(): str(p).strip().lower()
                        for k, p in json.loads(s).items()}
            pairs = {}
            for entry in s.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                domain, sep, provider = entry.partition("=")
                if not sep or not domain.strip() or not provider.strip():
                    raise ValueError(
                        f"ALLOWED_DOMAIN_PROVIDERS entry {entry!r} is not domain=provider"
                    )
                pairs[domain.strip().lower()] = provider.strip().lower()
            return pairs
        return v

    @property
    def domain_providers(self) -> dict[str, str]:
        """The effective domain -> required-provider table. Fails closed: empty = nobody."""
        if self.allowed_domain_providers:
            return self.allowed_domain_providers
        return {d: "google.com" for d in self.allowed_email_domains}

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

    @property
    def trace_salt_value(self) -> str:
        return self.trace_salt or self._secret(self.trace_salt_secret)


settings = Settings()
