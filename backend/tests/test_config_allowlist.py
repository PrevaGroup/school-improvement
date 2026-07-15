"""How ALLOWED_EMAIL_DOMAINS parses out of the environment.

Separate from test_security.py on purpose. Those tests monkeypatch
`settings.allowed_email_domains` directly, so they never exercise the env-var path — and the
first cut of this feature passed every one of them while being **completely broken in
production**: pydantic-settings runs `json.loads()` on complex fields *before* any validator,
so a plain "a.com,b.org" raised SettingsError at import and the app wouldn't start. The
`NoDecode` annotation in config.py is what fixes that, and these tests are what prove it.

Lesson worth keeping: a green unit test over a monkeypatched setting says nothing about
whether the setting can be *set*.
"""
import pytest

from app.config import Settings


def _domains(monkeypatch, value: str | None) -> set[str]:
    monkeypatch.delenv("ALLOWED_EMAIL_DOMAINS", raising=False)
    if value is not None:
        monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", value)
    monkeypatch.setenv("APP_DB_PASSWORD", "test-unused")
    return Settings().allowed_email_domains


def test_unset_admits_nobody(monkeypatch):
    """FAILS CLOSED. An unset allowlist must never mean "everyone": a deploy that forgets it
    should lock people out (loud, fixable), not open /api/chat and the Anthropic balance to
    anyone with a Google account (silent, expensive)."""
    assert _domains(monkeypatch, None) == set()


def test_comma_separated_is_the_supported_form(monkeypatch):
    """The form that survives `gcloud run deploy --set-env-vars`, which splits on commas
    itself — see backend/DEPLOY.md for the delimiter escape."""
    assert _domains(monkeypatch, "prevagroup.com,gatesfoundation.org") == {
        "prevagroup.com", "gatesfoundation.org",
    }


def test_whitespace_and_case_are_normalised(monkeypatch):
    """Lowercased at parse so the check in security.py can't be case-tricked."""
    assert _domains(monkeypatch, " PrevaGroup.com , GatesFoundation.ORG ") == {
        "prevagroup.com", "gatesfoundation.org",
    }


def test_json_form_is_tolerated(monkeypatch):
    """Someone will write JSON out of habit; don't punish it with a startup crash."""
    assert _domains(monkeypatch, '["prevagroup.com","gatesfoundation.org"]') == {
        "prevagroup.com", "gatesfoundation.org",
    }


@pytest.mark.parametrize("raw,expected", [
    ("prevagroup.com,,", {"prevagroup.com"}),      # trailing comma
    (",", set()),                                   # only separators
    ("   ", set()),                                 # whitespace only
    ("prevagroup.com", {"prevagroup.com"}),         # single, no comma
])
def test_ragged_input_does_not_produce_junk_domains(monkeypatch, raw, expected):
    """An empty-string domain in the set would be a real hazard: "" could match a malformed
    email's domain. Empties are dropped, never admitted."""
    assert _domains(monkeypatch, raw) == expected


def test_a_plain_string_does_not_crash_settings(monkeypatch):
    """Regression: without `NoDecode` this raised SettingsError at import — the app would not
    boot at all, and no test in test_security.py would have noticed."""
    Settings()  # must not raise
    assert _domains(monkeypatch, "prevagroup.com") == {"prevagroup.com"}
