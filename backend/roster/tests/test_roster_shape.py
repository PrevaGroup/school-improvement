"""The roster's shape, and the properties the authorisation layer depends on.

Checked against the mapped columns and the migration's SQL rather than a live database. The point
is not that SQLAlchemy works — it is that an edit which quietly weakens the access edge, or drops
the dating that roster overlap is computed from, fails here with a message saying why it mattered.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from roster.models import (RELEASE_ROLES, STAFF_ROLES, Enrollment, Section, SectionStaff,
                           Student)

MIGRATION = (pathlib.Path(__file__).resolve().parent.parent
             / "migrations" / "0009_roster_tables.py")
SQL = MIGRATION.read_text(encoding="utf8")


def _migration():
    spec = importlib.util.spec_from_file_location("roster_0009", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# The authorisation edge
# --------------------------------------------------------------------------- #
def test_staff_edge_is_keyed_on_a_hash_not_an_email():
    """This table answers 'which of your students is this', which makes it the one worth most to
    an attacker. It should be worth as little as possible when read."""
    cols = {c.name for c in SectionStaff.__table__.columns}
    assert "principal_hash" in cols
    assert not {c for c in cols if "email" in c or "address" in c}, (
        f"an identifying column appeared on the access edge: {sorted(cols)}")


def test_roles_are_a_closed_set():
    names = {c.name for c in SectionStaff.__table__.constraints if c.name}
    assert "ck_roster_section_staff_role" in names, (
        "role is unconstrained — a typo would silently create a role nothing grants")
    assert set(STAFF_ROLES) == {"teacher", "co_teacher", "coach"}


def test_a_coach_cannot_release():
    """A coach reads the class-level readings. Release is the authority claim the product rests on
    and it belongs to the people who teach the class."""
    assert "coach" not in RELEASE_ROLES
    assert RELEASE_ROLES == {"teacher", "co_teacher"}


def test_resolver_reads_a_set_local_not_an_argument():
    """The principal must not be client-supplied. Same rule the tenant already follows: derived
    server-side from a verified identity, bound with SET LOCAL."""
    assert "current_setting('app.principal_hash', true)" in SQL
    assert "CREATE FUNCTION roster_visible_sections" in SQL


def test_resolver_fails_closed_on_an_unset_principal():
    """`nullif(..., '')` makes an unset principal NULL, and `principal_hash = NULL` matches nothing.
    A code path that forgot to say who it is sees nothing rather than everything."""
    assert "nullif(current_setting('app.principal_hash', true), '')" in SQL


def test_resolver_is_stable_and_invoker_rights():
    """STABLE lets the planner hoist it out of a per-row loop. It must NOT be SECURITY DEFINER —
    that would let it see past a policy that applies to the caller."""
    assert "LANGUAGE sql STABLE" in SQL
    assert "SECURITY DEFINER" not in SQL


def test_resolver_respects_the_validity_window():
    """A teacher who left mid-year stops seeing the class, without their review history being
    deleted."""
    assert "s.active_from <= current_date" in SQL
    assert "s.active_to   >= current_date" in SQL


# --------------------------------------------------------------------------- #
# Dating — where roster overlap comes from
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model", [Enrollment, SectionStaff])
def test_membership_is_dated_not_current_state(model):
    """Roster overlap between two scoring windows is computed from these dates. Collapsing them to
    current-state removes a number the growth figures are required to report beside them — and
    makes a transferred student's already-scored paper look like it belongs to nobody."""
    cols = {c.name for c in model.__table__.columns}
    assert {"active_from", "active_to"} <= cols, (
        f"{model.__tablename__} is current-state; roster overlap becomes uncomputable")


def test_student_id_is_distinct_from_the_key_that_resolved_it():
    """`student_id` is stable across sections and years — a growth interval pairs on window labels
    for the same student, so an id that turned over between years would end every longitudinal
    claim. The external key can change when a district re-keys; they are not the same column."""
    cols = {c.name for c in Student.__table__.columns}
    assert "student_id" in cols and "external_key_hash" in cols


# --------------------------------------------------------------------------- #
# What the shape deliberately does NOT decide
# --------------------------------------------------------------------------- #
def test_a_student_may_be_in_more_than_one_section():
    """Two enrollment rows. Which section a paper binds to is a declared rule, not a default —
    encoding it as a uniqueness constraint here would prejudge an open policy question."""
    uniques = {frozenset(c.columns.keys()) for c in Enrollment.__table__.constraints
               if c.__class__.__name__ == "UniqueConstraint"}
    assert frozenset({"student_id"}) not in uniques
    assert frozenset({"tenant_id", "student_id"}) not in uniques


def test_a_section_may_have_more_than_one_teacher():
    """Co-teaching. Both hold release rights; who is expected to review is a rule, not a schema
    constraint."""
    uniques = {frozenset(c.columns.keys()) for c in SectionStaff.__table__.constraints
               if c.__class__.__name__ == "UniqueConstraint"}
    assert frozenset({"section_id", "role"}) not in uniques
    assert frozenset({"section_id"}) not in uniques


def test_section_links_to_the_star_but_does_not_require_it():
    """A district roster does not always carry an NCES id, and a section with no school is still a
    section. Requiring the link would make the sync fail on ordinary data."""
    school = Section.__table__.columns["school_id"]
    assert school.nullable
    assert any(fk.column.table.name == "dim_school" for fk in school.foreign_keys)


# --------------------------------------------------------------------------- #
# Module hygiene
# --------------------------------------------------------------------------- #
def test_rls_is_not_switched_on_here():
    """Enabling RLS is a deliberate core move for when the subsystem first holds real student
    writing — not a side effect of this module existing. This migration supplies the resolver those
    policies will call; it must not enable them."""
    assert "ENABLE ROW LEVEL SECURITY" not in SQL.upper()
    assert "CREATE POLICY" not in SQL.upper()


def test_migration_follows_the_scoring_revision():
    m = _migration()
    assert (m.revision, m.down_revision) == ("0009", "0008")
