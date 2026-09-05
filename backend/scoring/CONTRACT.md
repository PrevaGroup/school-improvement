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

Models: `scoring/models.py`.

## Migration revisions owned
`0008_scoring_tables.py`.

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
