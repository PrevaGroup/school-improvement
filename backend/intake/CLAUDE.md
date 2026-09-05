# Working in `intake`

Depend only on `core`. `roster` and `registry` are read with SQL, not imported.

**Do not replace the assignment with a loop.** Per-file nearest-name matching looks simpler and is
worse: it duplicates students and cannot see that the arrangement as a whole is wrong. The solver is
the design.

**Do not let a name outbid an account.** `ACCOUNT_SCORE` is deliberately two orders of magnitude
above any similarity. The whole argument for the Docs-only constraint is that ownership resolves
identity by lookup rather than inference.

**Keep the five outcome lists apart.** Unmatched, missing, non-student and unreadable are four
different facts about a folder, and collapsing any two of them into "not scored" is how a teacher
comes to believe something the system never determined.

**`reconcile` stays pure.** No Drive client, no session. The caller supplies dicts, which is what
lets the hard part be tested without credentials.
