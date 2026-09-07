# pooling - CONTRACT

The **only** module that crosses the district threshold. An engine: it serves nothing, and the PM
console reads its tables as a principal with no tenant mapping.

It ships nearly empty on purpose. The seam - the boundary, the consent gate, the run audit - is what
would be expensive to retrofit. The job that fills the aggregate tables waits on a legal basis and
on enough consenting districts, and the suppression rule enforces its own timing: with a minimum
district count nothing can be emitted early by accident.

## Tables owned

| Table | Role |
|---|---|
| `pooling_aggregation_consent` | A district's agreement that aggregated results may reach the publisher, scoped and dated. Gates ENTRY to the frame, not the output |
| `pooling_aggregate_run` | What one run read, under which consent set, with which suppression parameters, and how many districts contributed - a count, never a list |

The `agg_*` tables are **not created yet**: their grain follows from the PM console data contract
and from suppression parameters that depend on the legal basis, both open.

## The rules, in order of how easily they are lost

1. **Loop, do not join.** Iterate districts, set the tenant for each, accumulate in application
   memory. Never one query across tenant rows. SIP forbids cross-tenant joins to keep the option of
   peeling a tenant into its own database - a loop survives that peel by becoming a loop over
   databases; a join does not.
2. **Consent gates entry, not output.** Filtering afterwards means the aggregate was computed over
   data the district had not agreed to share, and then discarded. Not the same thing.
3. **Revocation propagates backward.** Withdrawal removes the district's contribution from EXISTING
   aggregates by triggering recomputation. Forward-only revocation is cosmetic.
4. **Two axes of minimum cell size**, and **complementary suppression**: suppress cells identifiable
   by differencing, against siblings in the same run and against the same cell in prior runs.
   Publishing over four districts and then over three identifies the one that left - the failure
   that gets missed, because each figure looks safe alone.
5. **No identifiers, and no stable pseudonyms.** Not student, teacher, class or school. A per-run
   salted pseudonym where a distribution needs units; stable pseudonyms are a separate, higher
   consent bar because they permit a longitudinal profile of one teacher.
6. **Nothing flows back.** No pooled figure re-enters a district's scoring path, anchored level, or
   any scorer context. A comparison group reaching the scorer is norm-referencing at national scale.

## Access

The PM principal is **deliberately unmapped** to any tenant. `get_current_tenant` 403s when
unmapped, and under RLS every district-scoped table returns zero rows - so the failure mode of a
routing mistake is an empty screen, not a cross-organisation disclosure. That is why these two
tables carry no `tenant_id`: they belong to no district, which is the point.
