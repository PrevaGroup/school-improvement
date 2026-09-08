# measurement — CONTRACT

An **engine**, like `likeschools`. No serving surface; `serving` reads these tables with SQL.

The estimator arrived with Phase 6 (`measurement/mfrm.py`): person and rater measures, fit
statistics, and rater x subgroup bias interactions. The frame tables remain the thing that was
expensive to retrofit — a record of exactly which observations an estimate was computed over.

**Two estimators, because the design decides which is correct.** `fit` is joint maximum likelihood
over any number of raters. `paired_severity` is conditional maximum likelihood for exactly two, and
it exists because JMLE inflates the severity gap when each paper carries only two ratings —
measured at +0.86 against a true +0.50, shrinking to +0.46 by four raters. One human pool and one
model configuration is this project's actual design, so the biased case is the normal case, and
`paired_severity` eliminates the person measures algebraically rather than estimating them.

**Only the contrast is identifiable with two raters.** "The model is harsh" and "the humans are
lenient" are the same statement without an external anchor, and a bias interaction in one rater
appears as its mirror in the other. `fit` centres raters at zero, which is a convention rather than
a finding.

## Tables owned

| Table | Role |
|---|---|
| `estimation_frame` | **THE seam.** A versioned, reproducible definition of what an estimate is fitted over. Immutable once active — a change is a new version, not an edit |
| `estimation_frame_member` | The resolved membership: which score events this frame version actually admitted, with `enters_calibration` carried from each event |
| `measurement_deletion_tombstone` | A removed subject, and the frames that removal invalidated |

Models: `measurement/models.py`. Resolver: `measurement/frames.py`. Migration: `0010_measurement_frames.py`.

## Three sets, not two

- **the record** — every score event ever written
- **the frame** — observations legitimate enough to carry a measure against anchored parameters
- **the calibration** — the subset that moves item, rater and threshold estimates

`score_event.enters_calibration` stamps the third at write time. This module defines and resolves
the second. The frame decides what is measurable; the event decides what moves parameters, and
resolution carries that answer rather than revisiting it.

## Invariants

1. **An active frame's definition is frozen** (trigger). Status may move and resolve bookkeeping may
   be filled in; what the frame admits cannot change. A number published against version 3 has to
   keep meaning what it meant.
2. **A tombstone marks affected frames `stale` in the same transaction** (trigger). A nightly sweep
   would leave a window in which a published figure silently rests on observations that no longer
   exist.
3. **An unknown definition key raises.** A typo silently skipped produces a frame admitting more
   than its author intended, and the estimate that follows looks perfectly healthy.
4. **A definition names what it restricts.** Absent key = no constraint. Defaults that exclude would
   make a definition's meaning depend on the resolver's version — the opposite of reproducible.

## The admission policy is still open

`DEFINITION_KEYS` documents what a definition may say; it does **not** encode which answers are
right. Escalated scores, set-level overrides and formative mini-task scores each have a conservative
default to argue against, and those are open items. Freezing them into the schema would settle by
accident what should be settled on purpose. Drafts are the one part already decided: retained in the
frame, excluded from the calibration.
