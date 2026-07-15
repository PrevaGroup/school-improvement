"""Characterization tests for the peer matcher (`likeschools/build_peers.py`).

This module had **no tests**. It's the only genuinely algorithmic code in the repo — impute,
z-score, Ledoit-Wolf shrinkage, Mahalanobis kNN — and it fails in the worst way available: a
wrong peer set doesn't crash, it produces plausible, wrong comparisons. Every number the product
shows is framed "relative to similar schools", so if the peer set is wrong, so is the product,
silently.

The boundary and schema guards check this module's *shape*. Nothing checked its *math*.

`build_partition` is pure — dicts in, dicts out — so all of this runs with no database. Values
below were read off the current implementation, not derived from what it ought to do: this pins
today's behavior so the algorithm can be rewritten deliberately (which is the whole point of the
module seam) rather than by accident.

Reading the low_confidence tests: three separate conditions OR together —
`n_imputed > 2`, `k_eff < k`, `kth_dist > threshold`. They overlap on small inputs, so the tests
isolate them with `conf_pctile=100.0`, which makes the threshold the *max* observed kth distance
and therefore un-exceedable (`>` is strict). That's a test lever, not a production setting.
"""
from __future__ import annotations

import inspect
import math

import pytest

from likeschools.build_peers import (
    CORE,
    FEATURES,
    build_partition,
    level_bucket,
    load_schools,
    locale_onehot,
)

CITY = (1.0, 0.0, 0.0, 0.0)


def school(sid: str, sed, el, swd, enroll, locale=CITY) -> dict:
    """A row shaped the way load_schools() emits them."""
    return {
        "school_id": sid,
        "school_year": "2024-25",
        "level_bucket": "High",
        "f_econ_disadv": sed,
        "f_el": el,
        "f_swd": swd,
        "f_enroll_log": math.log1p(enroll) if enroll is not None else None,
        "locale": locale,
    }


# Two tight pairs: A~B (small, low-poverty) and C~D (large, high-poverty). Any sane distance
# metric must pair A with B and C with D — that's the assertion these tests lean on.
def two_clusters() -> list[dict]:
    return [
        school("A", 50, 20, 10, 500),
        school("B", 52, 21, 11, 520),
        school("C", 90, 60, 30, 2000),
        school("D", 91, 61, 31, 2100),
    ]


# --------------------------------------------------------------------------- #
# D1 — the hard rule: never match on outcomes
# --------------------------------------------------------------------------- #
def test_match_vector_contains_no_outcome_metric():
    """Spec D1. Reading outcomes into the match vector breaks the entire premise.

    "Schools like you" must mean *demographically* alike, so that comparing outcomes across the
    peer set is meaningful. Match on an outcome and the comparison becomes circular — schools get
    matched to schools that already perform like them, and "you're doing worse than similar
    schools" quietly stops being a finding.
    """
    outcome_ish = ("absent", "chronic", "suspend", "suspension", "expul", "grad",
                   "college", "stability", "achieve", "proficien", "rate", "outcome")
    for feature in FEATURES:
        assert not any(word in feature.lower() for word in outcome_ish), (
            f"'{feature}' looks like an outcome. The match vector is inputs only (spec D1)."
        )


def test_the_matcher_never_reads_fact_metric():
    """D1 enforced at the source: the engine has no read access to outcomes, by construction.

    `fact_metric` is where every outcome lives. This module is architecturally prevented from
    matching on outcomes because it never selects from that table — that's the property worth
    keeping, not just the feature names above.
    """
    src = inspect.getsource(load_schools)
    assert "fact_metric" not in src, "the matcher must never read outcomes (spec D1)"
    assert "dim_school" in src, "match features come from dim_school inputs"


# --------------------------------------------------------------------------- #
# The peer list itself
# --------------------------------------------------------------------------- #
def test_a_school_is_never_its_own_peer():
    _, peers, _ = build_partition(two_clusters(), k=2, conf_pctile=90.0,
                                  run_year="2024-25", bucket="High")
    assert not [p for p in peers if p["school_id"] == p["peer_school_id"]]


def test_demographically_similar_schools_are_matched_first():
    """The one behavioral claim the product rests on: rank 1 is the most similar school."""
    _, peers, _ = build_partition(two_clusters(), k=2, conf_pctile=90.0,
                                  run_year="2024-25", bucket="High")
    nearest = {p["school_id"]: p["peer_school_id"] for p in peers if p["rank"] == 1}
    assert nearest["A"] == "B"
    assert nearest["B"] == "A"
    assert nearest["C"] == "D"
    assert nearest["D"] == "C"


def test_ranks_are_dense_from_1_and_ordered_by_increasing_distance():
    _, peers, _ = build_partition(two_clusters(), k=3, conf_pctile=90.0,
                                  run_year="2024-25", bucket="High")
    for sid in ("A", "B", "C", "D"):
        mine = sorted([p for p in peers if p["school_id"] == sid], key=lambda p: p["rank"])
        assert [p["rank"] for p in mine] == [1, 2, 3]
        distances = [p["distance"] for p in mine]
        assert distances == sorted(distances), f"{sid}: rank must follow distance"


def test_k_is_bounded_by_the_partition_size():
    """k_eff = min(k, n-1) — you cannot have more peers than there are other schools."""
    _, peers, stats = build_partition(two_clusters(), k=50, conf_pctile=90.0,
                                      run_year="2024-25", bucket="High")
    assert stats["k"] == 3                      # n=4 -> at most 3 others
    assert len(peers) == 4 * 3                  # every school gets a full list


def test_run_year_and_bucket_are_stamped_from_the_arguments():
    """The run-year label is the caller's, not the school's — one label per build (see the
    module docstring on avoiding fragmentation from mixed fact-stub years)."""
    feats, peers, stats = build_partition(two_clusters(), k=2, conf_pctile=90.0,
                                          run_year="2099-00", bucket="Primary")
    assert {f["school_year"] for f in feats} == {"2099-00"}
    assert {p["school_year"] for p in peers} == {"2099-00"}
    assert {p["level_bucket"] for p in peers} == {"Primary"}
    assert stats["school_year"] == "2099-00" and stats["level_bucket"] == "Primary"


# --------------------------------------------------------------------------- #
# Imputation
# --------------------------------------------------------------------------- #
def test_missing_features_are_imputed_to_the_within_partition_median():
    rows = [school("A", None, 20, 10, 500),
            school("B", 52, 21, 11, 520),
            school("C", 90, 60, 30, 2000)]
    feats, _, _ = build_partition(rows, k=2, conf_pctile=90.0, run_year="y", bucket="High")
    a = next(f for f in feats if f["school_id"] == "A")
    assert a["f_econ_disadv"] == 71.0        # median(52, 90) — A's own null is excluded
    assert a["n_imputed"] == 1


def test_n_imputed_counts_only_the_core_continuous_features():
    rows = [school("A", None, None, None, None),
            school("B", 52, 21, 11, 520),
            school("C", 90, 60, 30, 2000)]
    feats, _, _ = build_partition(rows, k=2, conf_pctile=90.0, run_year="y", bucket="High")
    a = next(f for f in feats if f["school_id"] == "A")
    assert a["n_imputed"] == len(CORE) == 4   # locale is one-hot, never imputed


def test_build_partition_mutates_the_rows_it_is_given():
    """Documented, not endorsed: imputation writes back into the caller's dicts.

    `main()` gets away with it because it hands each partition its own rows and never reuses
    them. Anything that reuses a row list across calls would silently feed the *previous*
    partition's medians into the next one — pinned here so a refactor has to notice.
    """
    rows = [school("A", None, 20, 10, 500),
            school("B", 52, 21, 11, 520),
            school("C", 90, 60, 30, 2000)]
    build_partition(rows, k=2, conf_pctile=90.0, run_year="y", bucket="High")
    assert rows[0]["f_econ_disadv"] == 71.0   # the caller's dict was overwritten
    assert "n_imputed" in rows[0]


# --------------------------------------------------------------------------- #
# low_confidence — three OR-ed triggers, isolated one at a time
# --------------------------------------------------------------------------- #
def test_no_low_confidence_when_nothing_is_wrong():
    """Baseline: full k, nothing imputed, threshold un-exceedable."""
    _, peers, _ = build_partition(two_clusters(), k=3, conf_pctile=100.0,
                                  run_year="y", bucket="High")
    assert not any(p["low_confidence"] for p in peers)


def test_a_thin_partition_makes_every_school_low_confidence():
    """k_eff < k: asking for 50 peers in a 4-school partition. Everyone is flagged, because
    nobody got the peer set that was asked for."""
    _, peers, _ = build_partition(two_clusters(), k=50, conf_pctile=100.0,
                                  run_year="y", bucket="High")
    assert all(p["low_confidence"] for p in peers)


def test_heavily_imputed_school_is_low_confidence_but_its_neighbours_are_not():
    """n_imputed > 2: a school matched mostly on made-up medians isn't really matched.

    The flag is per-school, not per-partition — B/C/D keep clean peer sets even though A's is
    unreliable.
    """
    rows = [school("A", None, None, None, 500),   # 3 imputed -> over the threshold
            school("B", 52, 21, 11, 520),
            school("C", 90, 60, 30, 2000),
            school("D", 91, 61, 31, 2100)]
    feats, peers, _ = build_partition(rows, k=3, conf_pctile=100.0, run_year="y", bucket="High")
    assert next(f for f in feats if f["school_id"] == "A")["n_imputed"] == 3
    low = {p["school_id"]: p["low_confidence"] for p in peers}
    assert low["A"] is True
    assert low["B"] is False and low["C"] is False and low["D"] is False


def test_two_imputed_features_is_not_yet_low_confidence():
    """The boundary is `> 2`, not `>= 2`. Pinned because it's an arbitrary cutoff that a
    refactor could shift without anyone noticing."""
    rows = [school("A", None, None, 10, 500),     # exactly 2 imputed
            school("B", 52, 21, 11, 520),
            school("C", 90, 60, 30, 2000),
            school("D", 91, 61, 31, 2100)]
    feats, peers, _ = build_partition(rows, k=3, conf_pctile=100.0, run_year="y", bucket="High")
    assert next(f for f in feats if f["school_id"] == "A")["n_imputed"] == 2
    assert not any(p["low_confidence"] for p in peers if p["school_id"] == "A")


def test_an_isolated_school_trips_the_distance_threshold():
    """kth_dist > percentile(conf_pctile): a school with no real neighbours gets flagged even
    though its list is full and nothing was imputed."""
    rows = [school("A", 50, 20, 10, 500),
            school("B", 51, 20, 10, 505),
            school("C", 52, 21, 11, 510),
            school("D", 99, 95, 60, 5000)]       # nothing like D in this partition
    _, peers, _ = build_partition(rows, k=2, conf_pctile=75.0, run_year="y", bucket="High")
    low = {p["school_id"]: p["low_confidence"] for p in peers}
    assert low["D"] is True, "the outlier's peers are far away — that's what the flag is for"


# --------------------------------------------------------------------------- #
# Numerical guards
# --------------------------------------------------------------------------- #
def test_zero_variance_features_do_not_produce_nan_distances():
    """Every school here is 'city', so the four locale columns have sd = 0.

    Without the `sd == 0 -> 1.0` guard this divides by zero and every distance becomes NaN —
    which would sort into a silently arbitrary peer order rather than raising.
    """
    _, peers, stats = build_partition(two_clusters(), k=2, conf_pctile=90.0,
                                      run_year="y", bucket="High")
    assert stats["sds"][4:] == [0.0, 0.0, 0.0, 0.0]       # the locale one-hots
    assert all(math.isfinite(p["distance"]) for p in peers)


def test_identical_schools_are_at_distance_zero():
    rows = [school("A", 50, 20, 10, 500),
            school("A_twin", 50, 20, 10, 500),
            school("C", 90, 60, 30, 2000),
            school("D", 91, 61, 31, 2100)]
    _, peers, _ = build_partition(rows, k=1, conf_pctile=90.0, run_year="y", bucket="High")
    nearest = next(p for p in peers if p["school_id"] == "A")
    assert nearest["peer_school_id"] == "A_twin"
    assert nearest["distance"] == pytest.approx(0.0, abs=1e-9)


def test_distance_is_symmetric_between_a_pair():
    _, peers, _ = build_partition(two_clusters(), k=3, conf_pctile=90.0,
                                  run_year="y", bucket="High")
    d = {(p["school_id"], p["peer_school_id"]): p["distance"] for p in peers}
    assert d[("A", "B")] == pytest.approx(d[("B", "A")])
    assert d[("C", "D")] == pytest.approx(d[("D", "C")])


# --------------------------------------------------------------------------- #
# model_partition_stats — the reproducibility contract
# --------------------------------------------------------------------------- #
def test_precision_matrix_reshapes_by_feature_count():
    """`models.py` promises: "stored row-major flattened; reshape to
    (len(feature_names), len(feature_names))". Anyone auditing a past run relies on that, and
    a mismatch would reshape into silent garbage rather than error.
    """
    _, _, stats = build_partition(two_clusters(), k=2, conf_pctile=90.0,
                                  run_year="y", bucket="High")
    n = len(stats["feature_names"])
    assert stats["feature_names"] == FEATURES
    assert len(stats["precision_mat"]) == n * n
    assert len(stats["means"]) == n and len(stats["sds"]) == n
    assert 0.0 <= stats["shrinkage"] <= 1.0


# --------------------------------------------------------------------------- #
# Bucketing / encoding — cheap, and they decide which schools are comparable at all
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw, expected", [
    ("Elementary", "Primary"), ("primary", "Primary"),
    ("Middle", "Middle"), ("Intermediate", "Middle"), ("Junior High", "Middle"),
    ("High", "High"), ("Senior High School", "High"),
    ("K-12 Combination", "Combined-Other"), ("k-8", "Combined-Other"), ("span", "Combined-Other"),
    (None, "Combined-Other"), ("", "Combined-Other"), ("   ", "Combined-Other"),
    ("Something Unrecognised", "Combined-Other"),
])
def test_level_bucket(raw, expected):
    assert level_bucket(raw) == expected


def test_junior_high_is_middle_not_high():
    """'Junior High' contains 'high'. Order of checks decides this, so it's worth a test:
    misfiling middle schools into the High partition would compare 7th-graders to seniors."""
    assert level_bucket("Junior High") == "Middle"


@pytest.mark.parametrize("raw, expected", [
    ("City", (1.0, 0.0, 0.0, 0.0)), ("1-Large City", (1.0, 0.0, 0.0, 0.0)),
    ("Suburb", (0.0, 1.0, 0.0, 0.0)), ("21", (0.0, 1.0, 0.0, 0.0)),
    ("Town", (0.0, 0.0, 1.0, 0.0)), ("3", (0.0, 0.0, 1.0, 0.0)),
    ("Rural", (0.0, 0.0, 0.0, 1.0)), ("43", (0.0, 0.0, 0.0, 1.0)),
    (None, (0.0, 0.0, 0.0, 0.0)), ("", (0.0, 0.0, 0.0, 0.0)),
    ("Unknown", (0.0, 0.0, 0.0, 0.0)),
])
def test_locale_onehot(raw, expected):
    assert locale_onehot(raw) == expected


def test_unknown_locale_is_all_zeros_not_an_error():
    """An unrecognised locale encodes as "none of the four" rather than raising. It's a real
    state — some rows have no locale — and a zero vector is honest about that instead of
    guessing a category."""
    assert locale_onehot("Antarctica") == (0.0, 0.0, 0.0, 0.0)
    assert sum(locale_onehot(None)) == 0.0
