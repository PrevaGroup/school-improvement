"""`_shared._engine()` picks its connection path from INSTANCE_CONNECTION_NAME.

Same contract as `app/db.py._build_engine` (the API's engine): set -> Cloud SQL Python
Connector over pg8000 (Cloud Run Jobs), unset -> the Auth-Proxy URL (Cloud Shell/local).
The connector itself is faked — these tests assert the *selection*, not Google's client.
"""
from public_metrics import _shared


class _FakeConnector:
    instances = 0

    def __init__(self, *a, **k):
        _FakeConnector.instances += 1

    def connect(self, *a, **k):  # never called here — engines are lazy
        raise AssertionError("no real connection in unit tests")


def test_default_is_the_auth_proxy_url(monkeypatch):
    # conftest fakes only the app password; the migrator one would go to Secret Manager
    monkeypatch.setattr(_shared.settings, "migration_db_password", "test-not-a-secret")
    monkeypatch.setattr(_shared.settings, "instance_connection_name", None)
    eng = _shared._engine()
    assert eng.url.drivername == "postgresql+psycopg"
    assert eng.url.host == _shared.settings.db_host      # 127.0.0.1 unless overridden


def test_instance_connection_name_switches_to_the_connector(monkeypatch):
    import google.cloud.sql.connector as gcsc

    monkeypatch.setattr(_shared.settings, "migration_db_password", "test-not-a-secret")
    monkeypatch.setattr(_shared.settings, "instance_connection_name", "p:us-central1:i")
    monkeypatch.setattr(gcsc, "Connector", _FakeConnector)
    before = _FakeConnector.instances
    eng = _shared._engine()
    assert eng.url.drivername == "postgresql+pg8000"     # creator-based, no host in URL
    assert eng.url.host is None
    assert _FakeConnector.instances == before + 1        # connector built eagerly, once
