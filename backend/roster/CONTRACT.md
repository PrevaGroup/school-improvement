# roster — CONTRACT

An **engine**. No serving surface. Rows come from a Classroom / SIS sync; nothing here is authored
by hand. Rewrite the sync however you like as long as these shapes hold.

## Tables owned (declares AND writes; all tenant-scoped)

| Table | Role |
|---|---|
| `roster_section_staff` | **THE authorisation edge.** Which principal may act on which section, in which role. Keyed on `principal_hash` — no email is stored |
| `roster_enrollment` | A student in a section over a validity window. Dated, not current-state: roster overlap between two scoring windows is computed from these dates |
| `roster_student` | A student, with an id stable across sections and years, distinct from the roster key that resolved them |
| `roster_section` | One class in one term. Scopes student matching, rubric version, and who reviews |

Models: `roster/models.py`. Migration: `0009_roster_tables.py`.

## The resolver

`roster_visible_sections(required_role text DEFAULT NULL)` returns the sections the current
principal may act on. Reads `app.principal_hash`, set with `SET LOCAL` beside `app.tenant` — the
client never supplies it. **An unset principal returns no rows**: a code path that forgot to say who
it is sees nothing rather than everything.

It exists as SQL rather than Python because it is the predicate RLS policies will use, and a policy
cannot call application code. That is the whole argument for the second authorisation layer: a bug
leaking one teacher's students to another inside a district deserves the same defence as a
cross-district leak, which means the database.

## What this module does NOT decide

Two policy questions the shape supports and deliberately does not answer — both need a declared
rule before a real deployment, and both are on the open items list:

- **A student enrolled in more than one section.** Two enrollment rows. Which section a paper binds
  to is a rule, not a default.
- **A co-taught section.** Two `teacher`/`co_teacher` rows, both with release rights. Who is
  expected to review is a rule, not a default.

Encoding either as a uniqueness constraint would prejudge it, and getting it wrong in the schema is
more expensive than leaving it to policy.

## Tenancy

All four tables carry `TenantMixin` and are **not yet in `PRIVATE_TABLES`**. Enabling RLS — here and
on the `scoring` tables — is a deliberate `core` move for when the subsystem first holds real
student writing, not a side effect of a module existing. This migration supplies the resolver those
policies will call so that enabling them is a policy statement rather than a redesign.
