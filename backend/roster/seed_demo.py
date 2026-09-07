"""Seed the section and students the fixture papers belong to.

    python -m roster.seed_demo
    python -m roster.seed_demo --purge

Intake matches a file to a student against the roster, so without one every paper comes back
unresolved and nothing scores. That is correct behaviour and a useless demo.

WHY THE ROSTER HOLDS MORE STUDENTS THAN THERE ARE PAPERS. Six students, three papers. A roster the
same size as the folder makes the reconciliation look easy in a way it never is: the assignment
solver's job is to pick the right student out of a class, and a class of exactly the people who
handed in is not a test of anything. It also makes `missing_students` real — the three who did not
hand in are a fact a teacher wants, and a demo where everyone submits never shows it.

`roster_student.display_name` is the only matching signal here. Account matching — the `looked_up`
path, which is the strong one — needs an email on the roster and there is no column for it yet.
Until there is, every match in this demo is `inferred`, and the `inferred_rate` on the manifest
will read 1.0. That is honest rather than broken: it is exactly what a folder of files with no
owner metadata looks like, and it is what a local folder IS.
"""
from __future__ import annotations

import argparse
import json
import uuid

from sqlalchemy import text

from ._db import engine

NS = uuid.UUID("6f2a1c94-0d3b-4f8e-9a71-5c2d8e4b17aa")

SECTION_ID = "section-11b-period4"
SECTION_NAME = "Gov 11B, period 4"

# Three who handed in, three who did not. The reconciler has to tell them apart.
STUDENTS = [
    "Maya Okonkwo",
    "Devon Ruiz",
    "Ji-woo Han",
    "Amara Beltrán",
    "Sam Delgado",
    "Priya Raman",
]


def student_id(name: str) -> str:
    return str(uuid.uuid5(NS, f"student:{name}"))


def seed() -> dict:
    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        conn.execute(text("""
            INSERT INTO roster_section (section_id, name, term_label, subject, external_key,
                                        tenant_id, visibility)
            VALUES (:s, :n, 'fall 2026', 'social studies', 'fixture-11b',
                    'public', 'public')
            ON CONFLICT (section_id) DO NOTHING"""),
            {"s": SECTION_ID, "n": SECTION_NAME})

        seeded = {}
        for name in STUDENTS:
            sid = student_id(name)
            seeded[name] = sid
            conn.execute(text("""
                INSERT INTO roster_student (student_id, display_name, grade, tenant_id, visibility)
                VALUES (:i, :n, '11', 'public', 'public')
                ON CONFLICT (student_id) DO NOTHING"""), {"i": sid, "n": name})
            conn.execute(text("""
                INSERT INTO roster_enrollment (enrollment_id, section_id, student_id, active_from,
                                               tenant_id, visibility)
                VALUES (:e, :s, :i, current_date, 'public', 'public')
                ON CONFLICT DO NOTHING"""),
                {"e": str(uuid.uuid5(NS, f"enrollment:{name}")), "s": SECTION_ID, "i": sid})
    return {"section_id": SECTION_ID, "students": seeded}


def purge() -> dict:
    counts = {}
    ids = [student_id(n) for n in STUDENTS]
    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        counts["roster_enrollment"] = conn.execute(text(
            "DELETE FROM roster_enrollment WHERE section_id = :s"), {"s": SECTION_ID}).rowcount
        counts["roster_student"] = conn.execute(text(
            "DELETE FROM roster_student WHERE student_id = ANY(CAST(:i AS text[]))"),
            {"i": ids}).rowcount
        counts["roster_section"] = conn.execute(text(
            "DELETE FROM roster_section WHERE section_id = :s"), {"s": SECTION_ID}).rowcount
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--purge", action="store_true")
    args = ap.parse_args()
    print(json.dumps(purge() if args.purge else seed(), indent=1))


if __name__ == "__main__":
    main()
