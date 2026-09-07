# intake - CONTRACT

Turning a folder into a manifest a teacher confirms once. An engine: it serves nothing.

Currently ships the deterministic half - roster reconciliation - because that is the part with the
decisions in it and the part that can be tested exhaustively without credentials. Drive enumeration,
Docs extraction and non-student classification arrive with the integration.

## What it produces

`reconcile(files, roster) -> Manifest`, holding five lists that mean five different things:

| | |
|---|---|
| `matched` | file to student, with **how** it was matched: `looked_up` or `inferred` |
| `unmatched_files` | a paper we could not place. A teacher corrects one binding key - cheap |
| `missing_students` | a fact about the class, not a gap in the matching |
| `non_student_files` | the prompt, the rubric, a blank template. Not a submission, and worth keeping - the prompt is the task statement |
| `unreadable_files` | an inventory discrepancy. A missing score and a file we cannot open mean different things |

## Why an assignment and not a loop

Matching twenty-eight documents to a thirty-student roster as **one** one-to-one assignment is
materially more accurate than twenty-eight nearest-name lookups. Independent lookups will assign two
papers to the same student and leave a third unexplained; a solver cannot, because the constraint is
in the solve. Two tests hold this: `test_assignment_beats_independent_lookups` and
`test_a_duplicate_cannot_happen`. If either stops passing, the design argument has been lost even
though the code still "works".

## Deterministic before probabilistic, and recorded

An account match is a **lookup**; a name read off a filename is an **inference**. Same assignment
step, different evidence, so every match carries `resolution_path`. A score whose binding was
inferred has a different error profile from one looked up - pooling them pools two populations - and
`Manifest.inferred_rate` is the earliest available signal that an integration has broken.

An account always outbids a name: `ACCOUNT_SCORE` is 100 against a similarity of at most 1.0, and
the gap is deliberate.

## No evidence is not a match

The solver has to pair something; that is not the same as having found something. Below
`NAME_FLOOR` a pairing is dropped and the file goes to `unmatched_files`. An unmatched paper costs a
teacher one correction; a paper matched to the wrong student attaches a score to the wrong
trajectory - and that is only cheap to repair because stage D never sees identity.
