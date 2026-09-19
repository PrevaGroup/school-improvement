"""Matching a folder of documents to a roster — as one assignment, not many lookups.

Design: agentic-scoring-pipeline-design v0.06 §3.3 (run intake) and §3.1.5 (class is a property of
the data path).

THE WHOLE POINT IS THAT THIS IS ONE DECISION. Matching twenty-eight documents to a thirty-student
roster as a one-to-one assignment is materially more accurate than twenty-eight independent
nearest-name lookups, and it is the difference between a system that says "this is probably Sam
Delgado" twenty-eight times and one that says "given all of it, here is the arrangement that fits".
Independent lookups will happily assign two papers to the same student and leave a third
unexplained; an assignment cannot, because the constraint is in the solver.

It also turns absence into information. Two students with nothing in the folder are a fact about
the class, not a gap in the matching — and a file nobody can read is an inventory discrepancy
rather than a missing paper. Those are three different things and the manifest keeps them apart.

DETERMINISTIC BEFORE PROBABILISTIC, AND THE DIFFERENCE IS RECORDED. An identity resolved by account
match is a LOOKUP; one recovered from a name on the page is an INFERENCE. They are the same
assignment step but not the same evidence, so every match carries how it was made. A score whose
binding was inferred has a different error profile from one looked up, and pooling them pools two
populations — which is also why a rising inferred rate is the earliest signal an integration has
broken.

Pure functions. No Drive client, no session: the caller supplies files and a roster as dicts, which
is what lets the hard part be tested exhaustively without credentials.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from scipy.optimize import linear_sum_assignment

# An account match is worth far more than any name similarity can be. The gap is deliberate and
# large: no amount of name agreement should ever outbid a verified account, because the whole
# argument for the Docs-only constraint is that ownership resolves identity by lookup.
ACCOUNT_SCORE = 100.0
EDITOR_SCORE = 60.0
# Below this, a name similarity is not evidence. A paper left unmatched is a teacher correcting one
# binding key; a paper matched to the wrong student is a score attached to the wrong trajectory,
# and the second is only cheap to repair because stage D never sees identity.
NAME_FLOOR = 0.72

LOOKED_UP, INFERRED = "looked_up", "inferred"


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]+", " ", s.lower()).strip()


def name_similarity(signal: str, student_name: str) -> float:
    """How much a signal looks like this student's name.

    Deliberately asymmetric, because the inputs are: `signal` is whatever was found — a filename, a
    line off the page — and `student_name` is the roster entry. Three readings, best wins:

      direct     the whole strings resemble each other
      reordered  'Delgado, Sam' is 'Sam Delgado'; a filename carries either form
      coverage   every token of the student's name appears somewhere in the signal

    Coverage is the one that matters in practice and the one a whole-string ratio gets wrong.
    'Maya Okonkwo - final draft' is unmistakably Maya's paper, and comparing it end to end scores
    0.63 because half the characters are about the draft rather than the student.
    """
    ns, nn = _norm_name(signal), _norm_name(student_name)
    if not ns or not nn:
        return 0.0
    direct = SequenceMatcher(None, ns, nn).ratio()
    reordered = SequenceMatcher(None, " ".join(sorted(ns.split())),
                                " ".join(sorted(nn.split()))).ratio()
    signal_tokens = ns.split()
    coverage = sum(max(SequenceMatcher(None, tok, st).ratio() for st in signal_tokens)
                   for tok in nn.split()) / len(nn.split())
    return max(direct, reordered, coverage)


@dataclass
class Match:
    file_id: str
    student_id: str
    score: float
    resolution_path: str          # looked_up | inferred
    basis: str                    # owner_account | editor_account | name


@dataclass
class Manifest:
    """What the teacher confirms once, for the whole set."""
    matched: list[Match] = field(default_factory=list)
    unmatched_files: list[str] = field(default_factory=list)
    missing_students: list[str] = field(default_factory=list)
    non_student_files: list[str] = field(default_factory=list)
    unreadable_files: list[str] = field(default_factory=list)

    @property
    def inferred_rate(self) -> float:
        """The integration-health signal. A rise here means account matching stopped working, and
        it will show up before anything else does."""
        if not self.matched:
            return 0.0
        return sum(m.resolution_path == INFERRED for m in self.matched) / len(self.matched)

    def summary(self) -> dict[str, Any]:
        return {"matched": len(self.matched),
                "looked_up": sum(m.resolution_path == LOOKED_UP for m in self.matched),
                "inferred": sum(m.resolution_path == INFERRED for m in self.matched),
                "unmatched_files": len(self.unmatched_files),
                "missing_students": len(self.missing_students),
                "non_student_files": len(self.non_student_files),
                "unreadable_files": len(self.unreadable_files)}


def _candidate(file: Mapping[str, Any], student: Mapping[str, Any]) -> tuple[float, str, str]:
    """Best evidence linking one file to one student, and what kind of evidence it is."""
    emails = {e.lower() for e in [student.get("email")] if e}
    owner = (file.get("owner_email") or "").lower()
    if owner and owner in emails:
        return ACCOUNT_SCORE, LOOKED_UP, "owner_account"

    # Where a teacher distributed copies from a template, ownership resolves to the teacher and
    # editor history is the fallback — still a lookup, still stronger than reading a name off the
    # page, but weaker than ownership because more than one person can edit a document.
    editors = {e.lower() for e in (file.get("editor_emails") or [])}
    if emails & editors:
        return EDITOR_SCORE, LOOKED_UP, "editor_account"

    best = max((name_similarity(n, student.get("display_name") or "")
                for n in (file.get("name_signals") or [])), default=0.0)
    if best >= NAME_FLOOR:
        return best, INFERRED, "name"
    return 0.0, INFERRED, "name"


def reconcile(files: Sequence[Mapping[str, Any]],
              roster: Sequence[Mapping[str, Any]]) -> Manifest:
    """One assignment over the whole set.

    `files` carry `file_id` and optionally `owner_email`, `editor_emails`, `name_signals`,
    `is_non_student` and `unreadable`. `roster` carries `student_id`, `display_name`, `email`.
    """
    m = Manifest()

    # Two categories that must not be silently dropped. A document we lack permission to read is an
    # inventory discrepancy, not an absence — a missing score and an unreadable file mean different
    # things to a teacher. And the assignment prompt or blank template is routinely in these
    # folders; it is not a submission, and it is worth keeping because it is the task statement.
    scoreable = []
    for f in files:
        if f.get("unreadable"):
            m.unreadable_files.append(f["file_id"])
        elif f.get("is_non_student"):
            m.non_student_files.append(f["file_id"])
        else:
            scoreable.append(f)

    if not scoreable or not roster:
        m.unmatched_files = [f["file_id"] for f in scoreable]
        m.missing_students = [s["student_id"] for s in roster]
        return m

    grid = [[_candidate(f, s) for s in roster] for f in scoreable]
    cost = [[-c[0] for c in row] for row in grid]
    rows, cols = linear_sum_assignment(cost)

    taken_students = set()
    for i, j in zip(rows, cols):
        score, path, basis = grid[i][j]
        if score <= 0:
            continue           # the solver had to pair something; no evidence is not a match
        m.matched.append(Match(scoreable[i]["file_id"], roster[j]["student_id"],
                               round(score, 4), path, basis))
        taken_students.add(roster[j]["student_id"])

    assigned_files = {x.file_id for x in m.matched}
    m.unmatched_files = [f["file_id"] for f in scoreable if f["file_id"] not in assigned_files]
    # Not a failure of matching. Two students with nothing in the folder is a fact about the class,
    # and the teacher wants to see it as one.
    m.missing_students = [s["student_id"] for s in roster if s["student_id"] not in taken_students]
    return m
