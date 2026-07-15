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
    dict(metric_id="homeless_enrollment", domain="demographics", display_name="Homeless Student Enrollment",
         unit="count", direction="context", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=False, data_origin="state"),
    dict(metric_id="enrollment", domain="demographics", display_name="Enrollment (Census Day)",
         unit="count", direction="context", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=False, data_origin="state"),
]

METRIC_IDS = [m["metric_id"] for m in METRICS]
STUDENT_GROUP_IDS = [g[0] for g in STUDENT_GROUPS]
