"""CA chronic absenteeism (2023-24) -> fact_metric.

    python -m etl.ca.load_ca_chronic_absenteeism --data-dir ~/data
"""
from etl.ca._shared import run_metric_loader

SPEC = dict(
    file="attendance/chronicabsenteeism_2023-24.txt",
    metric_id="chronic_absenteeism_rate", period_id="p2023-24",
    value_col="ChronicAbsenteeismRate",
    n_col="ChronicAbsenteeismEligibleCumulativeEnrollment",
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
