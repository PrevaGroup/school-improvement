"""Make `backend/` importable regardless of where pytest is launched from, so tests
can `import etl...` / `import app...` exactly as the ETL modules do at runtime
(each script also does `sys.path.append(.../backend)`; this mirrors it for collection).

Also supplies a throwaway DB password so the suite can be *collected* without any
credentials. `app/db.py` builds the engine at import time, which resolves
`settings.database_url` -> `app_db_password_value` -> Secret Manager. Without this,
importing anything under `app/` raises "No password available" and collection dies
before a single test runs. `create_engine()` opens no socket, so a fake password is
enough for any test that doesn't actually talk to Postgres.
"""
import os
import pathlib
import sys

_BACKEND = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))

# Only inject the fake when nothing else can resolve a password: an env var set here
# would outrank a real password in .env (pydantic-settings ranks env vars above the
# .env file), silently pointing a DB-backed test at the wrong credentials.
_env_file = _BACKEND / ".env"
_env_text = _env_file.read_text(encoding="utf-8") if _env_file.exists() else ""
_resolvable = any(
    key in os.environ or key in _env_text for key in ("APP_DB_PASSWORD", "GCP_PROJECT")
)
if not _resolvable:
    os.environ["APP_DB_PASSWORD"] = "pytest-not-a-real-password"
