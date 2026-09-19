# Working in `measurement`

Depend only on `core`. Never import another module — `scoring`'s events are read with SQL, and the
foreign key from `estimation_frame_member.event_id` is a table-level contract, not an import.

**Do not add estimator output tables yet.** Facet estimates, fit statistics and bias interactions
belong to Phase 6, when the estimator exists and its output shape is known rather than guessed. A
test asserts they are absent — delete it deliberately when the time comes, not incidentally.

**Keep `frames.py` pure.** No session, no database handle. The SQL that reads score events and
writes members belongs to the caller; the decision logic stays separable so it can be tested
exhaustively without a Postgres. That is why the resolver takes dicts.

**A definition names what it restricts.** If you are tempted to add a default that excludes
something, stop: it makes a stored definition's meaning depend on the resolver's version, and a
definition whose meaning drifts is not a definition. Put the conservative choice in the definition
an author writes.
