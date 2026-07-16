"""CA census-day enrollment (2024-25, count by subgroup) -> fact_metric.

    python -m public_metrics.load_ca_enrollment --data-dir ~/raw
"""
from ._shared import run_metric_loader

SPEC = dict(
    file="demographics/enrollment_censusday_2024-25.txt",
    metric_id="enrollment", period_id="p2024-25",
    value_col="TOTAL_ENR", n_col="TOTAL_ENR",
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
