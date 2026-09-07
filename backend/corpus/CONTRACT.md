# corpus - CONTRACT

The papers calibration is anchored on. Public reference content: no tenancy, identical for every
district, which is what lets two districts sit on one metric without a cross-tenant query.

**A separate module from `registry`, and the split is the write path.** The registry is authored - a
person defines what may be scored, on a release cadence, and the linter reads it. This is bulk ETL:
a corpus arrives with its scores already attached, needing conforming rather than reading, and the
loader follows `public_metrics/load_ca_*`.

## Tables owned

| Table | Role |
|---|---|
| `corpus_paper` | **THE seam.** One essay, with the demographics that make the fairness work possible before a real student exists |
| `corpus_score` | A score the corpus itself shipped - kept apart from `score_event` deliberately |
| `corpus_discourse_span` | Where an argumentative element sits. Segmentation without effectiveness |
| `corpus_source` | One corpus at one snapshot under one licence, and what it overlaps |

Models: `corpus/models.py`. Runner: `corpus/_shared.py`. Loader: `corpus/load_persuade.py`.

## What the corpus supplies, verified against the files

Essay text, ONE holistic score, demographics, and discourse spans. It does **not** supply trait
scores, element effectiveness, or **any rater identity**. So it anchors task and person parameters
and cannot anchor rater severity - the anonymous-pool problem. The human side of the connected
rating design is work to schedule, not data to acquire.

`corpus_score.rater_id` exists and is NULL for every row. The column is there so a corpus which does
ship rater identity loads without a migration, and so the absence is visible rather than inferred
from a missing column.

## The holdout is within the corpus, by paper

An earlier draft proposed calibrating on one anchor set and validating on another. The files show
ASAP2 shares 12,725 essays with PERSUADE at identical scores, and every ASAP prompt is already a
PERSUADE prompt - that split would have been half-circular.

`partition` is assigned by a deterministic hash of source and external id. Not random, not
stratified: stratifying on demographics would make the holdout depend on the labels the fairness
analysis is about to test, and a seeded shuffle would make the split an artefact of load order.

## Why scores stay out of `score_event`

These are one anonymous human judgment on a scale that is not ours. Folding them into the score
record would put observations with no rater identity into a table whose whole purpose is that every
observation has one.
