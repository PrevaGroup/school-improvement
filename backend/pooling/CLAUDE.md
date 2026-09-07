# Working in `pooling`

Depend only on `core`. This module is the exception the boundary test exists to keep honest: it is
the single place cross-tenant iteration is permitted, and `pooling/tests/test_seam.py` asserts no
other module does it.

**Never write a query that joins across tenants.** Iterate: set `app.tenant` per district and
accumulate in Python. A join here silently spends the option to peel a district into its own
database, which SIP holds deliberately and which a real FERPA contract may require.

**No table in this module may carry an identifier.** Not student, teacher, class, school, artifact
or tenant. `FORBIDDEN_KEYS` in `models.py` lists them and a test enforces it - because the wall is a
property of the data, not of the screens. A screen that wanted to drill could not be built if the
column does not exist.

**Do not create the `agg_*` tables until the suppression parameters are settled.** Their grain
depends on the legal basis and on minimum cell sizes, both open. A table created early is a shape
frozen before the question that determines it has an answer.
