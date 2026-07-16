"""CA student stability rate (2023-24) -> fact_metric.

    python -m public_metrics.load_ca_stability --data-dir ~/raw
"""
from ._shared import run_metric_loader

SPEC = dict(
    file="demographics/mobility_stability_2023-24.txt",
    metric_id="stability_rate", period_id="p2023-24",
    value_col="Stability Rate (percent)", n_col="Adjusted Cumulative Enrollment",
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
