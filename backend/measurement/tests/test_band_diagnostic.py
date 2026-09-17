"""The two decision rules, and the verdict the module exists to reach.

Pure functions over constructed inputs, like `test_frames.py` — no session, no Postgres. The
point of constructing them is that the two worlds the diagnostic must tell apart can both be
built on purpose, and the verdict checked against each.
"""
from __future__ import annotations

from measurement.band_diagnostic import (analyse, expected, level_at, separation, sweep,
                                         top_band_signal)

CATS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def _row(human, bands, ours=None, status="scored"):
    return {"paper": f"p{human}", "human": float(human), "ours": ours, "status": status,
            "bands": bands, "cats": CATS, "expected": expected(bands, CATS), "violations": 0,
            "threshold_used": 0.5}


def _discriminating(human):
    """A model that CAN see the top band but keeps every probability under 0.5.

    P(>=k) falls away above the paper's true level, and the top-band probability rises with the
    human score — 0.05 at the bottom, 0.45 at the top. Nothing clears the shipped threshold.
    """
    return {c: round(max(0.02, min(0.99, 0.95 - 0.28 * (c - human) - 0.02 * c)), 3)
            for c in CATS[1:]}


def _blind(human):
    """A model that cannot see the top band: P(>=6) is ~0.02 whatever the paper is like."""
    b = _discriminating(human)
    b[6.0] = 0.02
    b[5.0] = 0.05
    return b


# ------------------------------------------------------------------ the rules


def test_the_ladder_stops_at_the_first_rung_under_the_threshold():
    b = {2.0: 0.9, 3.0: 0.8, 4.0: 0.3, 5.0: 0.7, 6.0: 0.6}
    # 5 and 6 are confident and unreachable: "meets or exceeds 6" cannot hold while 4 fails.
    assert level_at(b, CATS, 0.5) == 3.0


def test_lowering_the_threshold_raises_the_level_and_never_lowers_it():
    b = _discriminating(4)
    levels = [level_at(b, CATS, t / 20) for t in range(1, 20)]
    assert levels == sorted(levels, reverse=True)


def test_the_expectation_spans_the_whole_scale():
    assert expected({c: 0.0 for c in CATS[1:]}, CATS) == 1.0
    assert expected({c: 1.0 for c in CATS[1:]}, CATS) == 6.0


def test_the_expectation_spends_a_band_the_ladder_discards():
    """The premise of the third column: probability under the threshold still counts."""
    b = {2.0: 0.99, 3.0: 0.99, 4.0: 0.49, 5.0: 0.40, 6.0: 0.30}
    assert level_at(b, CATS, 0.5) == 3.0
    assert expected(b, CATS) > 4.1


# ------------------------------------------------------------------ the verdict


def test_a_discriminating_model_reads_as_the_decision_rule():
    rows = [_row(h, _discriminating(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(6)]
    a = analyse(rows)
    assert a["top_band"]["d"] > 0.5
    assert "DECISION RULE" in a["verdict"] or "PARTIAL" in a["verdict"]


def test_a_blind_model_reads_as_the_model():
    rows = [_row(h, _blind(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(6)]
    a = analyse(rows)
    assert a["top_band"]["d"] < 0.5
    assert "READS AS THE MODEL" in a["verdict"]
    # The decisive consequence, and the reason the two verdicts route to different work:
    # no threshold anywhere in the sweep awards a 6.
    assert all(s["at_top"] == 0 for s in sweep(rows))


def test_the_blind_case_is_not_rescued_by_any_threshold():
    """What separates 'the cut point is wrong' from 'there is nothing to cut'."""
    rows = [_row(h, _blind(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(6)]
    assert max(s["at_top"] for s in sweep(rows)) == 0
    disc = [_row(h, _discriminating(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(6)]
    assert max(s["at_top"] for s in sweep(disc)) > 0


def test_too_few_top_papers_is_inconclusive_rather_than_a_finding():
    """Absence of evidence must not print as evidence of absence — the same rule the
    stop-condition module enforces with `insufficient`."""
    rows = [_row(h, _discriminating(h)) for h in (1, 2, 3) for _ in range(6)]
    assert "INCONCLUSIVE" in analyse(rows)["verdict"]


# ------------------------------------------------------------------ the table


def test_separation_rises_down_the_top_band_column_when_the_model_discriminates():
    rows = [_row(h, _discriminating(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(4)]
    col = [b["bands"][6.0] for b in separation(rows).values()]
    assert col == sorted(col), "P(>=6) must rise with the human score in the built case"


def test_separation_is_flat_when_the_model_is_blind():
    rows = [_row(h, _blind(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(4)]
    col = [b["bands"][6.0] for b in separation(rows).values()]
    assert max(col) - min(col) < 1e-9


def test_the_sweep_reports_the_top_count_beside_the_agreement():
    """A threshold can raise QWK and still never award a 6. Both numbers, always — the
    distinction the product requirement turns on."""
    rows = [_row(h, _discriminating(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(5)]
    s = sweep(rows)
    assert all("qwk" in x and "at_top" in x for x in s)
    assert [x["threshold"] for x in s] == sorted(x["threshold"] for x in s)


def test_top_band_signal_reports_the_ceiling_it_actually_saw():
    """`max_seen` answers 'could any threshold have awarded one' without reading the sweep."""
    rows = [_row(h, _blind(h)) for h in (1, 2, 3, 4, 5, 6) for _ in range(4)]
    assert top_band_signal(rows)["max_seen"] == 0.02


def test_a_perfectly_flat_top_band_is_a_finding_not_an_absence():
    """Zero variance with zero gap is the flattest column there is. Reporting it as nan would
    route the clearest possible 'the model cannot see it' to INCONCLUSIVE — absence of evidence
    printed as evidence of absence, backwards."""
    rows = [_row(h, {**_discriminating(h), 6.0: 0.02}) for h in (1, 2, 3, 4, 5, 6) for _ in range(6)]
    t = top_band_signal(rows)
    assert t["d"] == 0.0
    assert "READS AS THE MODEL" in analyse(rows)["verdict"]
