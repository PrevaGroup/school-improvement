# delivery - CONTRACT

What happened after a teacher said yes. `released` is a judgment; delivery is an I/O operation, and
the plan is explicit that they are different facts:

> "a hand-back can fail because the teacher no longer has edit access to a student's document, and
> that is recorded as **not sent** rather than silently as delivered. Released and delivered are
> different facts."

## Table owned

| Table | Role |
|---|---|
| `artifact_delivery` | One attempt to hand one message back. Append-only by trigger; a retry is a new row pointing at the one it follows |

Models: `delivery/models.py`. Runner: `delivery/deliver.py`. Migration: `0025_delivery_attempts.py`.

## Invariants

1. **Nothing goes out that a teacher has not released.** A trigger refuses an insert for an
   artifact in any other state. This module is one way to reach the table and a script is another,
   so the rule lives where both meet - the same argument as the release authority itself.
2. **Failures are rows.** A `failed` attempt must say what failed; a `sent` attempt must say where
   and when. A delivery that quietly did not happen is indistinguishable from one that did.
3. **Delivery is not a state of the artifact.** `artifact.state` ends at `released` and stays
   there. Folding a delivery failure into the state machine would let a transient network error
   move a paper out of `released`, and a state machine with a retry loop in it has stopped being a
   record of decisions.
4. **The record survives supersession.** Not bookkeeping: "the student received feedback on the
   superseded draft - that is what makes the next draft feedback-mediated, and it is the only thing
   that lets a growth claim over that pair be qualified honestly."
5. **What was sent is hashed.** If a message is edited after delivery, that hash is the evidence of
   which version the student read.

## Channels

`file` writes beside the paper - real delivery to a real place, and what makes the path
demonstrable before Drive exists. `google_docs_comment` and `classroom` are the plan's two real
ones; neither asks a student to sign in, which is what keeps a consent and minor-account surface
out of the pilot.

Adding one means adding a function to `CHANNELS` and nothing else. A channel that raises produces a
`failed` row carrying the exception's own words - a delivery module that swallowed an error would
be the silence this exists to prevent.
