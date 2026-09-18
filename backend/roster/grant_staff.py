"""Put a person on the staff of a class — the only way anyone reaches student work.

    python -m roster.grant_staff --email teacher@district.org --section section-11b-period4
    python -m roster.grant_staff --uid <identity platform uid> --section ... --role co_teacher
    python -m roster.grant_staff --email ... --section ... --revoke
    python -m roster.grant_staff --section section-11b-period4 --list

Since migration 0041, a signed-in person sees a paper only if an active `roster_section_staff` row
names them on that paper's section. In a deployment those rows come from the Classroom / SIS sync;
until there is one, and for the fixture class, this is how a row gets written — by a named person
at a terminal, as the migrator role, which is the same footing as `intake.confirm`.

## Why it asks Identity Platform for the uid

A staff row stores `principal_hash`, the salted hash of the verified `sub`, never an email — see
`roster/models.py` for why. The `sub` is the Identity Platform uid, which nobody knows by heart, so
`--email` looks it up (`accounts:lookup`, with the operator's application-default credentials). A
person who has never signed in has no uid yet: they sign in once, get the "not on the staff of any
class" page, and then this finds them.

## Revoking dates the row, it does not delete it

`--revoke` sets `active_to` to yesterday. The row stays, so the record still shows that this person
reviewed this class until then — the same reason enrollment is dated rather than deleted.
"""
from __future__ import annotations

import argparse
import json
import uuid

from sqlalchemy import text

from app.config import settings
from app.security import principal_hash

from ._db import engine
from .models import STAFF_ROLES

_CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"

_SECTION = text("SELECT tenant_id, name FROM roster_section WHERE section_id = :s")

_ACTIVE = text("""
    SELECT section_staff_id FROM roster_section_staff
     WHERE section_id = :s AND principal_hash = :h AND role = :r
       AND (active_from IS NULL OR active_from <= current_date)
       AND (active_to   IS NULL OR active_to   >= current_date)
""")

_GRANT = text("""
    INSERT INTO roster_section_staff (section_staff_id, section_id, principal_hash, role,
                                      active_from, active_to, tenant_id, visibility)
    VALUES (:id, :s, :h, :r, current_date, :ends, :tenant, 'private')
    -- Revoked and granted again the same day: the span key (section, person, role, start) is the
    -- same, so reopen that row rather than fail. Its history is one day long either way.
    ON CONFLICT ON CONSTRAINT uq_roster_section_staff_span
    DO UPDATE SET active_to = EXCLUDED.active_to
    RETURNING section_staff_id
""")

# Ends every active assignment this person has on this class, in any role.
_REVOKE = text("""
    UPDATE roster_section_staff SET active_to = current_date - 1
     WHERE section_id = :s AND principal_hash = :h
       AND (active_to IS NULL OR active_to >= current_date)
""")

_LIST = text("""
    SELECT section_staff_id, principal_hash, role, active_from, active_to
      FROM roster_section_staff WHERE section_id = :s ORDER BY active_from NULLS FIRST
""")


def uid_for_email(email: str) -> str:
    """The Identity Platform uid for an address, or a SystemExit that says what to do."""
    import google.auth
    import httpx
    from google.auth.transport.requests import Request

    project = settings.gcp_project
    if not project:
        raise SystemExit("set GCP_PROJECT so the uid can be looked up, or pass --uid")
    creds, _ = google.auth.default(scopes=[_CLOUD_PLATFORM])
    creds.refresh(Request())
    r = httpx.post(
        f"https://identitytoolkit.googleapis.com/v1/projects/{project}/accounts:lookup",
        headers={"Authorization": f"Bearer {creds.token}", "x-goog-user-project": project},
        json={"email": [email]}, timeout=10.0)
    r.raise_for_status()
    users = r.json().get("users") or []
    if not users:
        raise SystemExit(f"{email} has never signed in, so there is no uid to hash yet. Ask them "
                         "to sign in once, then run this again.")
    return users[0]["localId"]


def grant(section_id: str, hashed: str, role: str, ends: str | None) -> dict:
    with engine().begin() as conn:
        section = conn.execute(_SECTION, {"s": section_id}).mappings().first()
        if section is None:
            raise SystemExit(f"no section {section_id!r}")
        existing = conn.execute(_ACTIVE, {"s": section_id, "h": hashed, "r": role}).first()
        if existing:
            return {"section_id": section_id, "role": role, "granted": False,
                    "note": f"already active as {existing[0]}"}
        staff_id = conn.execute(_GRANT, {"id": str(uuid.uuid4()), "s": section_id, "h": hashed,
                                         "r": role, "ends": ends,
                                         "tenant": section["tenant_id"]}).scalar_one()
    return {"section_id": section_id, "section": section["name"], "district": section["tenant_id"],
            "role": role, "granted": True, "section_staff_id": staff_id, "ends": ends}


def revoke(section_id: str, hashed: str) -> dict:
    with engine().begin() as conn:
        n = conn.execute(_REVOKE, {"s": section_id, "h": hashed}).rowcount
    return {"section_id": section_id, "assignments_ended": n}


def listing(section_id: str) -> list[dict]:
    with engine().begin() as conn:
        return [{k: (str(v) if v is not None else None) for k, v in r.items()}
                for r in conn.execute(_LIST, {"s": section_id}).mappings()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = ap.add_mutually_exclusive_group()
    who.add_argument("--email", help="looked up in Identity Platform for the uid")
    who.add_argument("--uid", help="the Identity Platform uid (the token's `sub`)")
    ap.add_argument("--section", required=True)
    ap.add_argument("--role", default="teacher", choices=STAFF_ROLES)
    ap.add_argument("--ends", default=None, help="last day of the assignment, YYYY-MM-DD")
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--revoke", action="store_true")
    action.add_argument("--list", action="store_true", help="every staff row on the section")
    args = ap.parse_args()

    if args.list:
        print(json.dumps(listing(args.section), indent=1))
        return
    if not (args.email or args.uid):
        ap.error("name the person with --email or --uid")

    uid = args.uid or uid_for_email(args.email.strip().lower())
    hashed = principal_hash({"sub": uid})
    result = revoke(args.section, hashed) if args.revoke else grant(
        args.section, hashed, args.role, args.ends)
    print(json.dumps({"who": args.email or args.uid, **result}, indent=1))


if __name__ == "__main__":
    main()
