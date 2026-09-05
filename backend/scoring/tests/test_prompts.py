"""The prompts are half the rater's identity, so editing one has to be a deliberate act.

`test_the_prompt_fingerprint_is_pinned` is the whole point of this file. Change a word in
prompts.py and it fails, which forces the version bump into the same commit as the edit — and a
configuration promoted against the old version then refuses to run rather than quietly scoring
papers with a rater nobody approved.

If you are here because that test failed: you changed a prompt. Bump EVIDENCE_VERSION or
SCORE_VERSION, paste the new hash below, and promote a new scoring configuration. Do not just
paste the hash.
"""
from __future__ import annotations

import pytest

from scoring.prompts import (EVIDENCE_SCHEMA, EVIDENCE_VERSION, SCORE_SCHEMA, SCORE_VERSION,
                             fingerprint, render_scale)

PINNED = {
    "evidence": {"version": "ev.1", "sha256": "05264504a54983f7"},
    "score": {"version": "sc.1", "sha256": "97f36f59d676de80"},
}


def test_the_prompt_fingerprint_is_pinned():
    assert fingerprint() == PINNED, (
        "a prompt changed. That is a change to the rater, not to a string: bump the version in "
        "prompts.py, update PINNED here, and promote a new scoring configuration. Scores written "
        "either side of this edit are not from the same rater.")


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
