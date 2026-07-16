"""CA College-Going Rate, 16 months (2021-22) -> fact_metric.

Filters CompleterType='TA' (total) — the file splits each school x group into
completer-type variants that would otherwise collide on the fact key.

    python -m public_metrics.load_ca_college_going --data-dir ~/raw
"""
from ._shared import run_metric_loader

SPEC = dict(
    file="academics/collegegoingrate_16mo_2021-22.txt",
    metric_id="college_going_rate", period_id="p2021-22",
    value_col="College Going Rate - Total (16 Months)", n_col="High School Completers",
    where={"CompleterType": "TA"},
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
