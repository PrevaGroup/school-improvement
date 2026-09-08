"""The diagnostic reads spans that `scoring` writes, and it may not import `scoring` to do it.

`measurement` depends only on `core`, so `span_diagnostic.span_text` has to know the shape of a
verified span without sharing a definition with the code that produces it. That is a duplication,
and duplication without a check is drift with a delay on it.

This is the check, and it exists because the drift already happened: the first version read
`"text"` where `verify_all` writes `"span"`, so every span measured zero characters. It did not
error. It printed a clean flat column and a nan correlation — which is precisely what a genuine
"the evidence stage is blind" result looks like. A parse failure indistinguishable from a finding
is the worst kind, and it cost a run to notice.
"""
from __future__ import annotations

from measurement.span_diagnostic import span_text, volume
from scoring.verify import verify_all

PAPER = ("The Court held that student speech may be limited when it disrupts school. "
         "Tinker set the standard that schools must show substantial disruption.")


def test_the_diagnostic_reads_the_text_out_of_a_real_verified_span():
    kept, _ = verify_all(["Tinker set the standard"], PAPER)
    assert kept, "the fixture must actually verify, or this proves nothing"
    assert span_text(kept[0]) == "Tinker set the standard"


def test_volume_counts_real_characters_from_a_real_evidence_dict():
    proposed = ["Tinker set the standard", "a sentence that is not in the paper"]
    kept, dropped = verify_all(proposed, PAPER)
    evidence = {"proposed": len(proposed), "kept": kept, "dropped": dropped}

    v = volume(evidence)
    assert v["proposed"] == 2
    assert v["kept"] == 1
    assert v["chars"] == len("Tinker set the standard")


def test_a_dropped_span_contributes_nothing():
    """Only what survived verification reached stage D, so only that can explain a level."""
    _, dropped = verify_all(["a sentence that is not in the paper"], PAPER)
    assert dropped
    assert volume({"proposed": 1, "kept": [], "dropped": dropped})["chars"] == 0
