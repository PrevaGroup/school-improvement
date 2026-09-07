# scoring — CONTRACT

The record the writing subsystem is built around. `serving` reads these tables with SQL and owns
none of them; the pipeline writes them. Rewrite the pipeline however you like — different stages,
different prompts, a different model entirely — and nothing downstream notices, as long as this
contract holds.

## Tables owned (declares AND writes)

| Table | Role |
|---|---|
| `score_event` | **THE seam.** One immutable judgment about one criterion of one artifact. Append-only, enforced by trigger. Carries the full facet stamp: binding key, node, rubric version, **form variant as a separate column**, scoring configuration, scorer type and individual identity, scrutiny, outcome, calibration membership, lineage, idempotency key |
| `artifact` | One submitted document under one binding key, in one state. Holds the state machine's current position and the supersession pointer |
| `artifact_state_transition` | Every state change with the actor who made it — the audit half of the machine |
| `artifact_transition_rule` | The legal moves, as data. Read by the trigger; mirrors `ARTIFACT_TRANSITIONS` in `models.py`, and a test asserts they agree |
| `artifact_composition` | The review packet, stored as the teacher saw it. Append-only by trigger |

Models: `scoring/models.py`.

## The pipeline

| File | Role |
|---|---|
| `verify.py` | Span verification - the deterministic gate. Exact substring, versioned normalization, no model involved |
| `prompts.py` | The prompt text, versioned AND fingerprinted. Half the rater's identity |
| `rater.py` | `RaterIdentity` (the configuration, as an object) and the model call behind a two-method protocol |
| `score.py` | Stage C then stage D, one criterion at a time. **Pure** - a function of (text, criteria, rater) |
| `run_scoring.py` | The driver: registry read, ids, transaction, state transition (`bound` -> `scored`) |
| `compose.py` | The review packet, and `scored` -> `composed` |

`score.py` is pure so the architectural properties can be asserted rather than instructed:
`tests/test_score.py` checks the assembled prompts for the absence of the student's text at stage D,
of any other criterion, and of any prior score. Those are properties of the context, and a property
of the context is checkable; an instruction to the model is not.

## Migration revisions owned
`0008_scoring_tables.py`, `0017_artifact_composition.py`.

## Why the packet is stored rather than derived on read

Nearly all of it IS derivable from `score_event`, and a stored copy of derivable data is normally a
second source of truth waiting to drift. It is not, here: `score_event` is append-only, so a teacher
override APPENDS. Re-deriving after a review produces a different packet than the one the teacher
was looking at when they decided, and what was in front of a person at the moment of judgment is not
derivable from anything.

## The prior-observations panel

Three filters stand between the record and the invitation to read a trend, and none is cosmetic:

- **Same node only.** A prior level is comparable only if it came from the same node - same
  standard, criterion, scale structure and grade band. Two criteria that both sound like "evidence"
  are two nodes. The identifier is the identity, so this is a join, not a judgment.
- **Measurement occasions only.** A draft is scored and is not an occasion. A draft level beside a
  final one reads as growth within an assignment, and a draft is not a valid comparison point.
- **The rater is named and a change is flagged.** The pin holds within one section x task x
  iteration. Across tasks it does not, so two priors can be two raters; raw levels from two raters
  are not directly comparable. `prior_rater_mismatch` and a plain-English `prior_note` carry that
  qualification into whatever renders the packet.

Dropped spans reach the packet as a COUNT, never as text. Showing a teacher the sentences a model
invented invites reading the invention as evidence; `score_event` keeps the full text for whoever is
debugging the pipeline rather than reviewing a paper.

## What the driver reads, and what it refuses

Reads `registry_*` and writes nothing there - SQL only, never an import (the boundary rule; a
produced table is the contract).

Three refusals, all stops rather than warnings:

1. **A configuration whose prompt text has moved.** `registry_scoring_configuration` stamps prompt
   versions and hashes; `prompts.fingerprint()` computes them from the text on disk. A mismatch
   means the rater is not the one an administrator promoted.
2. **An ambiguous rater.** Two active configurations for a key, or two published versions of a node.
   Both are now impossible in the database (0014), and both are still checked where they are read.
3. **Two configurations already inside one section x task x iteration.** The damage is done; a third
   set of scores does not help.

## The configuration pin is derived, not stored

A configuration must not change inside one section x task x iteration - a teacher looking at their
class's scores is looking at one rater's work, or the comparison means nothing. There is **no pin
table**: the pin is read back out of `score_event`, the only place that cannot drift from what
actually happened. A scope that already has scores keeps their configuration even after it has been
superseded; a new scope takes the active one, and that becomes the pin by being written.

## Invariants this module guarantees

1. **A score is never updated.** `UPDATE` and `DELETE` on `score_event` raise. An override appends
   a new event referencing the prior one via `supersedes_event_id`.
2. **Only a teacher may reach `released`.** Enforced by trigger against `app.actor_type`, set with
   `SET LOCAL` beside `app.tenant`. An unset actor is `machine` — a code path that forgot to say
   who it is cannot release.
3. **Override and supersession are different relations.** `score_event.supersedes_event_id` is a
   different judgment about the same text; `artifact.superseded_by_artifact_id` is a different
   text under the same binding key. Nothing is deleted in either case.
4. **A level exists if and only if the status is `scored`.** Abstentions, no-verified-evidence and
   not-scorable outcomes carry no number — collapsing them into a blank or a zero is how a
   gradebook comes to assert things nobody decided.
5. **`idempotency_key` is unique.** A resumed run cannot double the observations for papers it had
   already finished.

## Vocabulary

`status` is drawn from `core`'s `vocab.SCORE_STATUSES`; `vocab.SCORE_STATUS_TO_VALUE_STATUS` maps a
released score into the star's `value_status` if and when the aggregation bridge is built. Adding a
status is a `core` change.

## Tenancy

`artifact`, `score_event` and `artifact_state_transition` carry `TenantMixin` and are **not yet in
`PRIVATE_TABLES`**. Enabling RLS is a deliberate `core` move made when the subsystem first holds
real student writing — not a side effect of this module existing. Same posture as `evals`.
