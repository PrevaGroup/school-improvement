"""The diagnostic that decides which stage the compression comes from."""
from __future__ import annotations

import math

from measurement.span_diagnostic import analyse, bands, render, volume


def _row(paper, human, ours, chars, kept=2, proposed=3, trait="Holistic", status="scored"):
    return {"paper": paper, "trait": trait, "status": status, "ours": ours,
            "human": float(human), "kept": kept, "chars": chars, "proposed": proposed}


def test_evidence_is_read_from_what_was_already_stored():
    """No model is called. `kept` is what survived substring verification and so is what stage D
    actually saw; `proposed` sits beside it because a high proposal count with a low keep rate is
    a model inventing quotations, which would otherwise look like a model finding nothing."""
    v = volume({"proposed": 5, "kept": ["the cat sat", "on the mat"], "dropped": ["invented"]})
    assert v == {"proposed": 5, "kept": 2, "chars": 21}


def test_spans_stored_as_objects_are_measured_too():
    """Verification writes span dicts in some paths and bare strings in others."""
    assert volume({"proposed": 2, "kept": [{"text": "abcd"}, "ef"]})["chars"] == 6


def test_missing_evidence_is_zero_not_an_error():
    assert volume(None)["kept"] == 0
    assert volume({})["chars"] == 0


# ------------------------------------------------------------------ the reading

def test_evidence_that_tracks_quality_but_not_our_score_reads_as_stage_d():
    """The signal arrives and is discarded — so per-descriptor scoring targets the failing step."""
    # chars rises with the human score; our level takes both values at every human score, so it
    # is uncorrelated with the evidence by construction rather than by luck.
    rows = [_row(f"p{h}-{o}", h, o, chars=h * 100)
            for h in (1, 2, 3, 4, 5, 6) for o in (2.0, 4.0)]
    out = render(rows)
    assert "READS AS STAGE D" in out


def test_evidence_that_tracks_nothing_reads_as_stage_c():
    """The level follows the evidence faithfully and the evidence is blind, so redesigning the
    level decision would be a day spent on the wrong stage."""
    # Every human score gets both evidence volumes, so evidence carries exactly no information
    # about writing quality — and our level follows the evidence perfectly.
    rows = [_row(f"p{h}-{c}", h, c / 100.0, chars=c)
            for h in (1, 2, 3, 4, 5, 6) for c in (200, 400)]
    out = render(rows)
    assert "READS AS STAGE C" in out


def test_a_middling_result_says_so_rather_than_picking_a_side():
    """Evidence volume is a crude proxy. When it cannot separate the stages, saying that is the
    honest output — picking one would send a day of work somewhere on a coin flip."""
    rows = [_row(f"p{i}", h, h * 0.4, chars=h * 40 + (i % 5) * 60)
            for i, h in enumerate([1, 2, 3, 4, 5, 6] * 6)]
    out = render(rows)
    assert "READS AS" in out


def test_no_rows_says_to_run_the_wave_first():
    assert "run the anchor wave first" in render([])


# ------------------------------------------------------------------ the table

def test_bands_group_by_the_human_score():
    rows = [_row("a", 1, 2.0, 100), _row("b", 1, 2.0, 200), _row("c", 6, 3.0, 900)]
    b = dict(bands(rows))
    assert b[1]["papers"] == 2 and b[1]["chars"] == 150.0
    assert b[6]["chars"] == 900.0


def test_abstentions_are_counted_and_not_averaged_into_our_score():
    """An abstention is not a zero. Averaging it in would drag our mean down and make the level
    stage look harsher than it is."""
    rows = [_row("a", 3, None, 100, status="no_verified_evidence"), _row("b", 3, 4.0, 100)]
    b = dict(bands(rows))
    assert b[3]["abstained"] == 1
    assert b[3]["ours"] == 4.0


def test_a_correlation_with_no_variance_is_undefined_not_zero():
    """Every paper carrying identical evidence is not "no relationship" — it is a question the
    data cannot answer, and 0.0 would read as an answer."""
    rows = [_row(f"p{i}", h, 3.0, chars=500) for i, h in enumerate([1, 2, 3, 4, 5, 6])]
    r, _ = analyse(rows)["overall"]["human_vs_evidence"]
    assert math.isnan(r)


def test_per_trait_is_reported_because_a_stage_can_fail_on_one_trait_only():
    rows = ([_row(f"p{i}", h, 3.0, h * 100, trait="Claim") for i, h in enumerate([1, 3, 5, 6])]
            + [_row(f"q{i}", h, 3.0, 400, trait="Lead") for i, h in enumerate([1, 3, 5, 6])])
    per = analyse(rows)["by_trait"]
    assert set(per) == {"Claim", "Lead"}
    assert per["Claim"]["n"] == 4
