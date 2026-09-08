"""Corpus papers into artifacts, and the things that must not leak either way.

The reason corpus papers become artifacts at all is that the severity we estimate has to describe
the rater that scores student writing. A paper that skipped the fit gate, skipped span
verification, or ran under a configuration nobody pinned characterises a different rater — and the
number would look exactly as legitimate.

The reason they carry their own tenant is the other direction: 664 PERSUADE essays in a teacher's
review queue would make the console useless.
"""
from __future__ import annotations

import json

from scoring.bind_corpus import (ITERATION, SECTION_ID, TASKS, TENANT, resolution_path, rows_for)


def paper(pid="p1", task="Independent"):
    return {"paper_id": pid, "text_hash": "h", "task_type": task,
            "source_id": "persuade20", "external_id": "E1"}


# ------------------------------------------------------------------ they cannot reach a teacher

def test_every_artifact_is_written_to_the_corpus_tenant():
    """Tenancy rather than a boolean and a `WHERE NOT is_corpus` in every query — a filter
    somebody forgets exactly once, in a query nobody reviews, and the failure is silent."""
    assert TENANT == "corpus"
    for r in rows_for([paper("a"), paper("b")], "run-1"):
        assert r["tenant_id"] == "corpus"


def test_no_corpus_paper_lands_in_the_public_tenant():
    assert all(r["tenant_id"] != "public" for r in rows_for([paper()], "run-1"))


# ------------------------------------------------------------------ the binding key

def test_the_task_id_follows_the_form_the_corpus_recorded():
    """Independent and text-dependent are different instruments. Scoring a source-based paper on
    the independent traits would measure the wrong construct and nothing would look wrong."""
    ind = rows_for([paper(task="Independent")], "r")[0]
    dep = rows_for([paper(task="Text dependent")], "r")[0]
    assert ind["task_id"] == TASKS["Independent"]
    assert dep["task_id"] == TASKS["Text dependent"]
    assert ind["task_id"] != dep["task_id"]


def test_a_paper_whose_form_is_unknown_is_not_bound():
    """Rather than defaulted to one of the two. A paper scored against the wrong instrument
    produces a severity estimate that is wrong in a way no fit statistic separates from noise."""
    assert rows_for([paper(task="Something else")], "r") == []
    assert rows_for([paper(task=None)], "r") == []


def test_the_student_id_is_the_de_identified_paper():
    """`bound` means somebody knows whose paper this is, and the state machine is right to insist.
    A PERSUADE essay was written by a real student whose identity nobody has — so the corpus id,
    never a fabricated name that would eventually be counted as a student."""
    r = rows_for([paper("paper-42")], "run-1")[0]
    assert r["student_id"] == "paper-42"
    assert r["section_id"] == SECTION_ID
    assert r["iteration"] == ITERATION


def test_the_source_uri_says_which_corpus_and_which_essay():
    r = rows_for([paper()], "run-1")[0]
    assert r["source_uri"] == "corpus:persuade20:E1"


def test_every_part_of_the_binding_is_declared():
    """Nothing was inferred from a filename or matched against a roster. Recording `declared`
    keeps `looked_up` meaning what it means everywhere else — an account matched an address — so
    `inferred_rate` stays a signal about the Drive integration rather than a mixture."""
    path = json.loads(rows_for([paper()], "run-1")[0]["resolution_path"])
    assert {path[k] for k in ("student", "section", "task", "iteration")} == {"declared"}
    assert path["basis"].startswith("corpus:")


def test_each_artifact_gets_its_own_id():
    ids = {r["artifact_id"] for r in rows_for([paper("a"), paper("b"), paper("c")], "r")}
    assert len(ids) == 3


# ------------------------------------------------------------------ the pipeline is not bypassed

def test_the_artifact_is_written_unbound_then_bound():
    """Through the state machine, not around it. The insert is `unbound` and a separate UPDATE
    makes the move, so the transition trigger sees it — the same path a teacher's resolve takes."""
    import inspect

    from scoring import bind_corpus

    src = inspect.getsource(bind_corpus)
    assert "'unbound', NULL" in src
    assert "SET state = 'bound'" in src
    assert "AND state = 'unbound'" in src


def test_it_does_not_write_score_events_or_compositions():
    """Binding is binding. If this module started producing scores it would be the second scoring
    path the tenant and the task exist to prevent."""
    import inspect

    from scoring import bind_corpus

    src = inspect.getsource(bind_corpus)
    assert "score_event" not in src
    assert "artifact_composition" not in src


def test_the_draw_arrives_over_stdin_rather_than_by_import():
    """`scoring` may not import `corpus` — modules integrate through produced tables and process
    boundaries. The boundary test caught the first version of this file reaching into
    `corpus.anchor` for the draw."""
    import ast
    import inspect
    import pathlib as _p

    from scoring import bind_corpus

    # The IMPORTS, not the prose. The docstring names `corpus.anchor` in order to say it is not
    # imported, and a grep cannot tell those apart — the same mistake this suite made once already
    # on a migration that explained why NOT to write a blanket grant.
    tree = ast.parse(_p.Path(bind_corpus.__file__).read_text(encoding="utf8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert "corpus" not in imported, f"imports {sorted(imported)}"
    assert "json.load(sys.stdin)" in inspect.getsource(bind_corpus)


# ------------------------------------------------------------------ waves

def test_a_second_wave_does_not_recreate_the_first():
    """The anchor set is scored in waves and wave 1 is a subset of wave 2. Re-binding a paper
    would give it two artifacts, two sets of scores, and double its weight in every estimate."""
    import inspect

    from scoring import bind_corpus

    src = inspect.getsource(bind_corpus.bind)
    assert "already" in src
    assert "p[\"paper_id\"] not in already" in src
