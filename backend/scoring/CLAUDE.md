# Working in `scoring`

Depend only on `core` (`app.models`, `app.vocab`, `app.db`, `app.security`). Never import another
module — the AST boundary test fails CI on the first crossing.

Three things to know before editing:

**The trigger is the enforcement, not the application.** "Only a teacher may release" lives in
`0008_scoring_tables.py`, not in a router. If you find yourself adding an `if user.is_teacher`
check in Python to protect a transition, the trigger already did it — and a rule that exists in
both places will eventually disagree with itself.

**`ARTIFACT_TRANSITIONS` in `models.py` is duplicated in the migration on purpose.** A migration
must be readable and runnable at the revision it was written, without importing code that has since
moved. `tests/test_state_machine.py` asserts the two agree; if you change one, change both and let
the test tell you when you forgot.

**Widening the facet stamp is cheap; narrowing it is not.** Facets not logged now are unrecoverable
later. If you are tempted to drop a column because nothing reads it yet, check whether a measurement
question would need it — the whole reason this table is wide is that the construct audit found
hidden facets in existing rubric data that could not be recovered after the fact.
