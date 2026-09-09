"""The prompts are half the rater's identity, so editing one has to be a deliberate act.

`test_the_prompt_fingerprint_is_pinned` is the whole point of this file. Change a word in
prompts.py and it fails, which forces the version bump into the same commit as the edit — and a
configuration promoted against the old version then refuses to run rather than quietly scoring
papers with a rater nobody approved.

If you are here because that test failed: you changed a prompt. Bump FIT_VERSION,
EVIDENCE_VERSION or SCORE_VERSION, paste the new hash below, and promote a new scoring
configuration. Do not just paste the hash.

ADDING a stage does the same thing, and should. When the fit gate arrived, every configuration
already in the database stopped matching and refused to run — correctly, because a rater that now
decides admissibility before scoring is not the rater those configurations named.
"""
from __future__ import annotations

import pytest

from scoring.prompts import (EVIDENCE_SCHEMA, EVIDENCE_VERSION, FEEDBACK_VERSION, FIT_SCHEMA,
                             FIT_VERSION, SCORE_SCHEMA, SCORE_VERSION, feedback_fingerprint,
                             fingerprint, render_scale)

PINNED = {
    "fit": {"version": "fit.1", "sha256": "2338d95dcc9f0219"},
    # ev.2: the evidence stage now answers whether the criterion is PRESENT, and receives the
    # source text when the assignment supplied one.
    "evidence": {"version": "ev.2", "sha256": "756c49cdef3e3a1b"},
    # sc.2 / bd.2: both stage-D forms receive the source text.
    "score": {"version": "sc.2", "sha256": "22d49f6ba3d255c4"},
}

PINNED_CUMULATIVE = {
    "fit": {"version": "fit.1", "sha256": "2338d95dcc9f0219"},
    "evidence": {"version": "ev.2", "sha256": "756c49cdef3e3a1b"},
    "band": {"version": "bd.2", "sha256": "ee607a6c4386648b"},
}


def test_the_cumulative_fingerprint_is_pinned_too():
    """It was not, and a prompt only one rater uses is exactly the one a pin would miss."""
    assert fingerprint("cumulative") == PINNED_CUMULATIVE, (
        "the band prompt changed. Same rule as below: bump the version, update the pin, promote a "
        "new configuration.")


def test_the_prompt_fingerprint_is_pinned():
    assert fingerprint() == PINNED, (
        "a prompt changed. That is a change to the rater, not to a string: bump the version in "
        "prompts.py, update PINNED here, and promote a new scoring configuration. Scores written "
        "either side of this edit are not from the same rater.")


PINNED_FEEDBACK = {"feedback": {"version": "fb.2", "sha256": "e5228cdca96513a8"}}


def test_the_feedback_prompt_is_pinned_too():
    """It had no pin when it was written, which was an omission rather than a decision — the
    scoring prompts had one from the start and this is the same discipline. A composition stamps
    this fingerprint, so an edit without a bump makes every stored stamp a claim about text that
    no longer exists."""
    assert feedback_fingerprint() == PINNED_FEEDBACK, (
        "the feedback prompt changed. Bump FEEDBACK_VERSION and update PINNED_FEEDBACK — messages "
        "drafted either side of this edit were not written by the same composer.")


def test_the_feedback_prompt_is_versioned_apart_from_the_rater():
    """A score's meaning does not change because a sentence in a feedback prompt improved. Folding
    the two together would make every wording fix invalidate a term of scores."""
    assert FEEDBACK_VERSION not in str(fingerprint())
    assert "evidence" not in feedback_fingerprint()


def test_the_version_travels_with_the_hash():
    """A version bumped without a text change, or the reverse, both break the pairing."""
    fp = fingerprint()
    assert fp["evidence"]["version"] == EVIDENCE_VERSION
    assert fp["score"]["version"] == SCORE_VERSION


def test_the_schemas_do_not_use_maxItems():
    """The API rejects `maxItems` inside a json_schema output format — found the hard way in the
    slice-1 prototype. The `0 to 5 spans` bound is instruction, and verification is what actually
    bounds what reaches stage D."""
    assert "maxItems" not in str(EVIDENCE_SCHEMA)
    assert "maxItems" not in str(SCORE_SCHEMA)


def test_a_list_descriptor_stays_a_list_of_clauses():
    """The observed C3 row stacks three conditional judgments in one cell. Joining them into prose
    hides exactly the thing two raters would score differently."""
    out = render_scale("c", {"1": "flat", "2": ["holds a claim", "cites a source"]}, [1, 2])
    assert "  - holds a claim" in out and "  - cites a source" in out
    assert "holds a claim, cites a source" not in out


def test_the_scale_order_comes_from_the_categories_not_the_dict():
    """The scale is the node's identity; a dict's key order is not."""
    out = render_scale("c", {"2": "mid", "1": "low", "3": "high"}, [1, 2, 3])
    assert out.index("Level 1") < out.index("Level 2") < out.index("Level 3")


def test_a_missing_descriptor_is_a_broken_node_not_a_gap_to_render_around():
    with pytest.raises(ValueError, match="no descriptor for category"):
        render_scale("c", {"1": "low"}, [1, 2])


# ------------------------------------------------------------------ what the API will accept

def test_no_schema_uses_a_range_keyword():
    """`minimum`/`maximum` on a number are refused at request time:

        output_config.format.schema: For 'number' type, properties maximum, minimum are not
        supported

    The cumulative wave shipped with them and failed on every paper AFTER paying for that paper's
    evidence calls — the failure is per request, so the money is spent before it is discovered.

    A schema is unexecuted text until a request carries it, which is the same shape as the SQL
    that passed by not being run. This catches the one keyword pair confirmed refused; the real
    protection is the one-paper smoke test before a wave, which was skipped that time.
    """
    import scoring.prompts as prompts

    schemas = {n: v for n, v in vars(prompts).items()
               if n.endswith("_SCHEMA") and isinstance(v, dict)}
    assert schemas, "no schemas found — this test would pass by finding nothing"

    def walk(node, path):
        if isinstance(node, dict):
            for bad in ("minimum", "maximum"):
                assert bad not in node, f"{path} uses {bad!r}, which the API refuses"
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    for name, schema in schemas.items():
        walk(schema, name)
