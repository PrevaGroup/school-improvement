# Working in `roster`

Depend only on `core`. Never import another module — the AST boundary test fails CI on the first
crossing. `scoring` and `intake` read these tables with SQL; that is the seam.

**Do not store an email.** `principal_hash` and `external_key_hash` are salted hashes, following
`usage_chat_daily`. This table answers "which of your students is this", which makes it the one an
attacker most wants to read — it should be worth as little as possible when read. `display_name` is
the deliberate exception: a teacher reviewing a paper needs to know whose it is.

**Dated rows, not current state.** Enrollment and staff rows carry `active_from` / `active_to`. A
student who transfers has an enrollment that ended, not one that never existed — and roster overlap
between scoring windows is computed from those dates, so collapsing them to current-state removes a
number the growth figures are required to report.

**Fail closed.** `roster_visible_sections()` returns nothing for an unset principal. If you find
yourself adding a branch that widens access when something is missing, that is the wrong direction:
the failure mode of a mistake here should be an empty screen.
