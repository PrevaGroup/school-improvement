# measurement

Which observations an estimate was fitted on — versioned, hashed, and rebuildable.

The estimator **arrived** with Phase 6 (`mfrm.py`). The frame tables are the record it is
reproducible from, built first because reproducibility is expensive to retrofit and deletion
propagation then comes almost free.

Read `CONTRACT.md` before changing a table shape, particularly the three-sets distinction.

## Diagnostics

Neither writes anything. Both read what the pipeline already persisted into `score_event`, so
they cost no model calls — which is the reason each was written instead of estimated as an
experiment.

| | Question |
|---|---|
| `span_diagnostic` | Which STAGE loses the signal — does stage C carry it, and does stage D use it? Answered stage D, which is what migration 0038 acted on |
| `band_diagnostic` | Why the top band is never awarded — can the model separate those papers at all (fix the decision rule), or not (fix the exemplars and the descriptor)? |

    python -m measurement.span_diagnostic
    python -m measurement.band_diagnostic

`band_diagnostic` covers `cumulative` raters only: a `category` configuration names a band in one
call and stores no probabilities, and a rater with no bands must not print like a rater whose
bands are flat.
