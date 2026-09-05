"""The conformed vocabulary — `core`'s shared yardsticks.

What every module must agree on to mean the same thing by "chronic absenteeism" or "English
Learners". These ids are the values that land in `dim_metric.metric_id` and
`dim_student_group.student_group_id`, and therefore the join keys in `fact_metric`. Two modules
disagreeing here doesn't raise an error — it silently produces wrong numbers.

Moved out of `etl/ca/_shared.py` 2026-07-15. Two modules need it and it belonged to neither:
public_metrics seeds the dims from it, and sip constrains the extractor to it (an LLM inventing
`metric_id="attendance"` would write rows that join to nothing). That made sip import
public_metrics — the last cross-module import in the repo. It isn't CA-specific, and it isn't
loader-specific; it's the contract, so it lives in core.

STAYS in public_metrics deliberately: `CDE_CATEGORY` (California's ReportingCategory codes ->
these ids) and `PERIODS`. Those are one state's mapping *into* this vocabulary, not the
vocabulary — a second state would bring its own crosswalk and reuse these ids unchanged. That
line is the whole point of "conformed": the yardstick is shared, the adapters are not.

Changing anything here is a `core` change (CLAUDE.md): every module reads it, and the ids are
already persisted as data. Adding a new metric/group is additive and safe; renaming or removing
an id orphans existing `fact_metric` rows and needs a migration, not an edit.
"""
from __future__ import annotations

# (student_group_id, label, dimension) -> seeds dim_student_group.
STUDENT_GROUPS = [
    ("all", "All Students", "total"),
    ("race_black", "Black/African American", "race"),
    ("race_amerind", "American Indian/Alaska Native", "race"),
    ("race_asian", "Asian", "race"),
    ("race_filipino", "Filipino", "race"),
    ("race_hispanic", "Hispanic/Latino", "race"),
    ("race_pacific", "Pacific Islander", "race"),
    ("race_two", "Two or More Races", "race"),
    ("race_white", "White", "race"),
    ("race_nr", "Not Reported", "race"),
    ("gender_f", "Female", "gender"),
    ("gender_m", "Male", "gender"),
    ("gender_x", "Non-Binary", "gender"),
    ("el", "English Learners", "eng_prof"),
    ("swd", "Students with Disabilities", "program"),
    ("sed", "Socioeconomically Disadvantaged", "ses"),
    ("migrant", "Migrant", "program"),
    ("foster", "Foster Youth", "program"),
    ("homeless", "Homeless", "program"),
]

# Seeds dim_metric. `direction` is what makes a number readable: it says which way is good, so
# a percentile can be turned into "better/worse than the band" (serving) and a plan's target can
# be judged (sip). Never assume higher = better.
METRICS = [
    dict(metric_id="chronic_absenteeism_rate", domain="attendance", display_name="Chronic Absenteeism Rate",
         unit="pct", direction="lower_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=True, data_origin="state"),
    dict(metric_id="suspension_rate", domain="behavior", display_name="Suspension Rate (Total)",
         unit="pct", direction="lower_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=True, data_origin="state"),
    dict(metric_id="expulsion_rate", domain="behavior", display_name="Expulsion Rate (Total)",
         unit="pct", direction="lower_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=True, data_origin="state"),
    dict(metric_id="grad_rate_acgr", domain="academics", display_name="Graduation Rate (ACGR)",
         unit="pct", direction="higher_better", grains="annual", applies_to_levels="HS",
         is_leading_indicator=False, data_origin="state"),
    dict(metric_id="stability_rate", domain="engagement", display_name="Stability Rate",
         unit="pct", direction="higher_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=True, data_origin="state"),
    dict(metric_id="college_going_rate", domain="academics", display_name="College-Going Rate (16 mo)",
         unit="pct", direction="higher_better", grains="annual", applies_to_levels="HS",
         is_leading_indicator=False, data_origin="state"),
    dict(metric_id="ela_met_standard_pct", domain="academics", display_name="ELA: Standard Met or Exceeded (CAASPP)",
         unit="pct", direction="higher_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=False, data_origin="state"),
    dict(metric_id="math_met_standard_pct", domain="academics", display_name="Math: Standard Met or Exceeded (CAASPP)",
         unit="pct", direction="higher_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=False, data_origin="state"),
    dict(metric_id="homeless_enrollment", domain="demographics", display_name="Homeless Student Enrollment",
         unit="count", direction="context", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=False, data_origin="state"),
    dict(metric_id="enrollment", domain="demographics", display_name="Enrollment (Census Day)",
         unit="count", direction="context", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=False, data_origin="state"),
]

METRIC_IDS = [m["metric_id"] for m in METRICS]
STUDENT_GROUP_IDS = [g[0] for g in STUDENT_GROUPS]

# --------------------------------------------------------------------------- #
# Missingness — the shared rule, and the two domains that follow it.
#
# Education data is mostly gaps, and the rule that keeps them honest is that a missing number is
# *unknown*, never zero, and never evidence that the thing itself is absent. That rule is the same
# whether the gap is a suppressed small-N cell in a state file or a criterion the scorer declined
# to score, so the vocabulary lives here rather than once per module.
#
# These were a trailing comment on `FactMetric.value_status` until 2026-09-04. A comment cannot be
# depended on: nothing stopped a second module inventing its own set and meaning something slightly
# different by "not collected". Naming them is what makes the rule enforceable.
#
# The column is `Text` with no CHECK constraint, deliberately — a status the loaders have not
# learned yet should land as data to be looked at, not as an insert that fails at 2am. Validation
# belongs in the writers, against these lists.
# --------------------------------------------------------------------------- #

# fact_metric.value_status — school × period × metric × group.
VALUE_STATUSES = [
    ("reported",       "A real number, measured and released."),
    ("suppressed",     "Exists; withheld for privacy, usually small-N."),
    ("no_students",    "The group is empty at this school — a true zero denominator, not a gap."),
    ("not_applicable", "The metric does not apply to this grade span or school type."),
    ("not_collected",  "In scope for collection, and not collected this period."),
    ("not_loaded",     "The source has it; we have not ingested it yet."),
    ("unknown",        "Cause of absence not established. The honest default."),
]

# score_event status — student × task × criterion × rater × occasion.
# A different grain and a different confidentiality class from fact_metric, so a separate column on
# a separate table (the writing subsystem does not extend the star). Same rule, mapped below.
SCORE_STATUSES = [
    ("scored",               "A real level, from verified evidence."),
    ("withheld",             "Exists; the teacher decided not to release it. Terminal."),
    ("not_scorable",         "A defined non-attempt against the bound task. Never imputed as low performance."),
    ("no_verified_evidence", "The criterion was in the frame and no span survived verification. Routes to a human; not a level."),
    ("abstained",            "The scorer declined. A routing decision inside the frame, never a missing cell."),
    ("unbound",              "We hold the artifact and cannot yet say what it is or whose."),
]

# How a released score aggregates into the star, when that bridge is built. One way only, above a
# suppression floor. `no_students` has no writing analogue: a class with no students submits nothing,
# which arrives as an empty run rather than as a status on a row that does not exist.
SCORE_STATUS_TO_VALUE_STATUS = {
    "scored":               "reported",
    "withheld":             "suppressed",
    "not_scorable":         "not_applicable",
    "no_verified_evidence": "not_collected",
    "abstained":            "unknown",
    "unbound":              "not_loaded",
}

VALUE_STATUS_IDS = [s[0] for s in VALUE_STATUSES]
SCORE_STATUS_IDS = [s[0] for s in SCORE_STATUSES]
