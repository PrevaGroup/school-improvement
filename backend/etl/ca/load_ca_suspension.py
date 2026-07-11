"""CA suspension (2023-24) -> fact_metric.

    python -m etl.ca.load_ca_suspension --data-dir ~/data
"""
from etl.ca._shared import run_metric_loader

SPEC = dict(
    file="behavior/suspension_2023-24.txt",
    metric_id="suspension_rate", period_id="p2023-24",
    value_col="Suspension Rate (Total)", n_col="CumulativeEnrollment",
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
