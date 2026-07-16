"""Seed the conformed dimensions + dim_school. Run ONCE before the fact loaders.

    python -m public_metrics.seed_ca_dims --data-dir ~/data
"""
from ._shared import run_seed

if __name__ == "__main__":
    run_seed()
