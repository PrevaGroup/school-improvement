# Working in `corpus`

Depend only on `core`. Never import another module.

**Do not invent a rater.** The corpus ships none, and `rater_id` is NULL on every row. Filling it
with a synthetic value would hide the single most consequential thing the files told us: severity is
not estimable from this corpus.

**Do not merge corpus scores into `score_event`.** One anonymous judgment on a scale that is not
ours does not belong in a table whose purpose is that every observation has an identified rater.

**Do not stratify the partition.** Stratifying on demographics makes the holdout depend on the
labels the fairness analysis is about to test. The hash is deliberate.

**Blank demographics stay NULL.** Letting blank become a value creates an 'unknown' subgroup in
every fairness table, and it would be the largest one.

**Record non-independence between sources.** `overlaps_source_id` exists because ASAP2 and PERSUADE
look like two corpora and are not. The next apparent second source deserves the same check before
anyone splits calibration across it.
