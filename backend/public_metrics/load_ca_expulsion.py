"""CA expulsion (2023-24) -> fact_metric.

    python -m public_metrics.load_ca_expulsion --data-dir ~/data
"""
from ._shared import run_metric_loader

SPEC = dict(
    file="behavior/expulsion_2023-24.txt",
    metric_id="expulsion_rate", period_id="p2023-24",
    value_col="Expulsion Rate (Total)", n_col="CumulativeEnrollment",
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
