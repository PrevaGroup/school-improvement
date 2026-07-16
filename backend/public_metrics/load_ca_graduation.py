"""CA graduation — Adjusted Cohort Graduation Rate (2024-25) -> fact_metric.

    python -m public_metrics.load_ca_graduation --data-dir ~/data
"""
from ._shared import run_metric_loader

SPEC = dict(
    file="academics/acgr_gradcohort_2024-25.txt",
    metric_id="grad_rate_acgr", period_id="p2024-25",
    value_col="Regular HS Diploma Graduates (Rate)", n_col="CohortStudents",
)

if __name__ == "__main__":
    run_metric_loader(SPEC)
