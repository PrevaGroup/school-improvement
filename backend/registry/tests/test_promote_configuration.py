"""Promoting a rater. The parts that do not need a database are the parts that decide things."""
from __future__ import annotations

from registry.config_hash import DEFAULT_ESCALATION, definition_hash, resolve_models

BASE = dict(model_id="claude-opus-5", effort="high",
            prompt_versions={"score": {"version": "sc.1", "sha256": "abc"}},
            normalization_version="1")


def test_two_configurations_describing_the_same_rater_collide():
    """`config_id` is not in the hash. That is how a replay proves it replayed the same thing
    rather than merely running under the same name."""
    assert definition_hash(**BASE) == definition_hash(**BASE)


def test_the_method_and_the_threshold_change_it():
    assert definition_hash(**BASE) != definition_hash(**BASE, level_method="cumulative")
    assert definition_hash(**BASE) != definition_hash(**BASE, level_threshold=0.6)


def test_declaring_no_escalation_is_the_default_policy_not_an_absence():
    """A configuration that declares nothing and one that spells out the defaults are the same
    rater; only one of them says so."""
    assert definition_hash(**BASE) == definition_hash(**BASE, escalation=dict(DEFAULT_ESCALATION))


def test_a_stage_override_changes_the_rater():
    assert definition_hash(**BASE) != definition_hash(
        **BASE, stage_models={"evidence": "claude-haiku-4-5-20251001"})


def test_declaring_the_same_model_at_every_stage_does_not():
    everywhere = {s: "claude-opus-5" for s in resolve_models("claude-opus-5", None)}
    assert definition_hash(**BASE) == definition_hash(**BASE, stage_models=everywhere)


def test_an_absent_stage_falls_back_to_the_base_model():
    m = resolve_models("claude-opus-5", {"evidence": "claude-haiku-4-5-20251001"})
    assert m["evidence"] == "claude-haiku-4-5-20251001"
    assert m["score"] == "claude-opus-5" and m["fit"] == "claude-opus-5"


def test_the_cli_refuses_a_fingerprint_stamped_for_the_other_method():
    """A configuration stamped with the wrong stage-D prompt is refused by `check_configuration`
    at the first paper. Catching it at promotion costs nothing and there is no reason to find out
    two hours into a wave."""
    import pathlib

    src = (pathlib.Path(__file__).parent.parent / "promote_configuration.py").read_text(
        encoding="utf8")
    assert 'expected = {"band"} if a.level_method == "cumulative" else {"score"}' in src


def test_the_promoter_and_the_rationale_are_required_arguments():
    """The database refuses an `active` configuration without both — a rater nobody approved
    cannot score. Requiring them at the CLI means the failure is an argparse message rather than
    an integrity error after a connection is open."""
    import pathlib

    src = (pathlib.Path(__file__).parent.parent / "promote_configuration.py").read_text(
        encoding="utf8")
    for flag in ("--promoted-by", "--rationale"):
        i = src.index(f'"{flag}"')
        assert "required=True" in src[i:i + 200], f"{flag} must be required"
