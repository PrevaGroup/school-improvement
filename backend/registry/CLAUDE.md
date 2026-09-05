# Working in `registry`

Depend only on `core`. Never import another module.

**Do not move `scale_categories` onto the version.** It sits on the node so that a category change
cannot be expressed as a new version - it has to be a new node. That placement IS the "one
identifier, one scale" rule; a trigger would be the weaker version of it.

**Do not add a harmonisation view.** If you are tempted to map two nodes onto a common scale, the
answer is that comparability lives on the person metric and the items were never on a common scale
to begin with. Collapsing within a node - seven categories to four, justified by that node's own
threshold evidence - is legitimate and different.

**Advisory findings must stay clearable only with a reason.** An advisory that can be dismissed
silently is a check that will be skipped, and the record will not show that anyone decided anything.

**The linter is pure functions over dicts.** No session, no database handle. The SQL that loads a
registry belongs to the caller; keeping the rules separable is what lets them be tested exhaustively
without a Postgres.
