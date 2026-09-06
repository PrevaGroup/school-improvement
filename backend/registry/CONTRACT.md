# registry - CONTRACT

What may be scored, and by which rater. Configuration in the pipeline design's sense: authored
before any run, applying to every artifact in scope, reviewed on a release cadence rather than per
artifact. It fails **silently and at scale** - one error reaches every paper in a section.

Public reference content: no tenancy. A node means the same thing in every district, which is what
makes cross-district anchoring possible without a cross-tenant query.

## Tables owned

| Table | Role |
|---|---|
| `registry_skill` | A SUB-STANDARD: a lettered part (X.1a) or a clause somebody split out of a compound standard. `derivation` says which, and a `clause` split names who made it |
| `registry_rubric` | One named instrument, with an identifier of its own. Until 0019 this was a prose string repeated on every trait |
| `registry_rubric_trait` | Which traits a rubric is made of. **Many-to-many** |
| `registry_node` | **THE trait.** One standard, one criterion, one scale, one grade band. The identifier is the identity; the composite is the integrity constraint |
| `registry_node_version` | Descriptors at a version. Frozen once published |
| `registry_task` | A thing students hand in. `ordinal` is taught position - an annotation, never an ordering principle for difficulty |
| `registry_scoring_site` | WHICH iterations of a task are scored, and whether each is the measurement occasion |
| `registry_scoring_site_node` | The trait set: which nodes a site is scored on. Frozen at binding, before stage C |
| `registry_scoring_configuration` | The rater, as a versioned object: model id, prompt versions, effort, normalization rules |

| `registry_lint_acknowledgment` | One recorded judgment about one advisory finding: which rule, which subject, the reason, and who |

Models: `registry/models.py`. Linter: `registry/lint.py`. Seed + publication: `registry/seed_demo.py`.
Migrations: `0012_registry_tables.py`, `0014_one_published_version.py`,
`0015_lint_acknowledgment.py`.

## Publication runs the linter

Versions insert as `draft`. The registry is then read BACK OUT of the database, lint runs against
what is actually stored, and only then do drafts become `published`. Linting the in-memory intent
would check what we meant to write rather than what is there.

Blocking findings refuse publication and leave the drafts, which is the useful failure state - a
draft can be fixed and a published version cannot.

Advisory findings clear only with a row in `registry_lint_acknowledgment`, which `lint()` reads
through `Registry.acknowledgments`. The reason is stored rather than the fact, because
"acknowledged" alone is indistinguishable from the check having been skipped - the difference the
two severity classes exist to preserve. A CHECK refuses a reason under twelve characters.

    python -m registry.seed_demo --acknowledge RULE SUBJECT REASON BY

This is NOT `registry_node_version.construct_unchanged_ack`, which answers one specific blocking
rule about a descriptor edit. One version can carry several acknowledgments here, each with its own
author and reason.

## Exactly one current row, in two places

Two partial unique indexes (0014), both found by writing the query that depends on them rather than
by designing the table:

- **One published version per node.** The scoring driver assembles a trait set by joining
  `registry_node_version` on `status = 'published'`. With two published versions the join returns
  the node twice - the artifact is scored on it twice, under two wordings, and the trait set
  recorded on the events no longer matches the one used. Nothing raised; the linter checks
  authoring quality, not this.
- **One active configuration per key.** Two active rows makes the rater ambiguous, and a rater that
  cannot be named cannot have a severity estimated.

Superseded, withdrawn and draft rows are untouched: the history stays, only the count of *current*
rows is bounded.

## What `scoring` reads from here

The scoring driver reads `registry_scoring_site`, `registry_scoring_site_node`, `registry_node`,
`registry_node_version` and `registry_scoring_configuration` **with SQL and never by import** - a
produced table is the contract. Those five table shapes are therefore load-bearing for the pipeline;
changing a column name in them breaks a consumer that no import graph will show you.

## The shape

    standard  ->  skill  ->  rubric  ->  trait  ->  criteria

A skill is a sub-standard. Either the document carries lettered parts and the skill is one of them
(a fact), or a compound standard was split into clauses by a person (a judgment, attributed). A
skill with no rubric is taught and NOT scored - `rubric_id` is nullable so the unscored case is
representable, or somebody invents a placeholder rubric and every coverage count is wrong.

**Rubric-to-trait is many-to-many, and that is load-bearing.** A trait is not owned by a rubric.
The same trait identifier appearing in two rubrics is how commonality gets DECLARED, and a trait
shared between rubrics is the anchor that places both on one metric. Own a trait to one rubric and
every rubric floats on its own scale.

## Identifiers mean nothing

`registry_skill.skill_id`, `registry_rubric.rubric_id` and `registry_node.node_id` are UUIDs, with a
CHECK. An identifier that encodes facts - `demo-ci` - invites people to read the facts off it, and
then the fact changes and the identifier is left asserting something false about a row nobody can
safely rename.

The readable name is `criterion_label`. The publisher's own short code is `external_ref`, so
CoreTools' `ci` never has to become an identity. The column stays `text` rather than `uuid` because
`score_event.node_id` holds millions of stamps eventually and the guarantee belongs where
identifiers are AUTHORED, not where they are recorded.

## The node rule

Identity is the identifier. `standard_code`, `grade_band` and `scale_categories` are attributes that
must agree everywhere it appears, which turns two classes of authoring error into mechanical checks.

- **Identifiers are immutable and never recycled.** Reassigning one makes every historical score
  stamped with it ambiguous.
- **One identifier, one scale structure.** Enforced by shape rather than by trigger: the scale sits
  on the node and descriptors on the version, so a category change cannot be a new version. It is a
  new node - the correct answer, because a difference in category count is evidence the rubrics drew
  the construct differently.
- **Commonality is declared, not discovered.** Two nodes are the same node when a product manager
  assigned them the same identifier against the same standard. Because that is an assertion, the
  data can refute it - a standing registry check, not a release gate.

## What is deliberately absent

No harmonised view across nodes and no machinery to build one. Comparability lives on the person
metric: a four-category node beside a five-category node needs no reconciliation, because both place
persons on the same logit continuum. The urge to harmonise is a raw-score instinct.

## The linter

Two classes. **Blocking** means the registry is internally incoherent - publication refused.
**Advisory** means a judgment the linter cannot make; it clears only with a recorded reason, and the
acknowledgment becomes part of the version record, so the next reader sees a judgment that was made
rather than a check that was skipped.

Blocking: identifier integrity, scale declared, strand substitution, anchor coverage in a linking
sequence, descriptor change without acknowledgment.
Advisory: taught but unscored, stacked conditionals, grade band coherence.

It does **not** flag scale structures differing across nodes. Six structures across seven
instruments is not an inconsistency - there was never one thing they were being inconsistent about.
