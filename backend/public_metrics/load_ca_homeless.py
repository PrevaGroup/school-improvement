"""CA homeless student enrollment (2023-24, count) -> fact_metric.

    python -m public_metrics.load_ca_homeless --data-dir ~/raw
"""
from ._shared import run_metric_loader

SPEC = dict(
    file="demographics/homeless_2023-24.txt",
    metric_id="homeless_enrollment", period_id="p2023-24",
    value_col="Homeless Student Enrollment", n_col="Cumulative Enrollment",
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
