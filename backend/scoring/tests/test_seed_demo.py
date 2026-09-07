"""The demo seed must not be able to touch anything real, and must agree with registry's half.

`--purge` scopes by `run_id`, so an artifact that escaped that scope would be both created and left
behind. Identifiers here NAME a run, which is different from a trait identifier: reference content
must have an identity that means nothing, while an operational row may say what produced it.

The cross-file agreement test is the price of the honest duplication: `scoring.seed_demo` names a
task that `registry.seed_demo` authors, and it may not import it (modules integrate through
tables). A binding key naming a task that does not exist is the demo failing at the trait-set read
with nothing useful to say about why.
"""
from __future__ import annotations

import inspect

import pytest

from registry import seed_demo as registry_seed
from scoring import seed_demo
from scoring.prompts import render_scale
from scoring.score import Criterion, build_evidence_prompt

LIFECYCLE_WORDS = ("demo", "test", "temp", "tmp", "sample", "dummy", "fake")


def test_the_two_halves_of_the_fixture_agree_on_the_binding():
    """The duplication is deliberate — registry may not be imported here — and this is what keeps
    it honest. A binding key naming a task that does not exist is the run failing at the trait-set
    read with nothing useful to say about why."""
    assert seed_demo.TASK_ID == registry_seed.TASK_ID
    assert seed_demo.CONFIG_KEY == registry_seed.CONFIG_KEY


def test_no_identifier_carries_a_lifecycle_word():
    """`demo-` put a lifecycle fact inside an identity, and `--purge` then matched on it, which
    made deletion depend on identity. A run id may name its run; nothing may be called demo."""
    ids = [seed_demo.RUN_ID, seed_demo.SECTION_ID, seed_demo.TASK_ID, seed_demo.CONFIG_KEY]
    offenders = [i for i in ids if any(w in i.lower() for w in LIFECYCLE_WORDS)]
    assert not offenders, f"identifiers carrying a lifecycle word: {offenders}"


def test_the_fixture_writes_files_and_creates_no_artifacts():
    """It used to insert artifacts directly, which meant the fixture exercised a path no real
    paper takes. Papers now arrive through `intake.read_folder` and become artifacts through
    `scoring.bind`, so the fixture's only job is to put files somewhere."""
    src = inspect.getsource(seed_demo.seed)
    assert "INSERT INTO artifact" not in src
    assert "write_text" in src


def test_the_filenames_are_the_ones_students_actually_use():
    """The filename IS the matching signal when a local folder carries no owner metadata. A
    fixture writing `maya.txt` would test nothing about the reconciliation that matters."""
    for paper in seed_demo.load()["papers"].values():
        assert paper.get("filename"), "every fixture paper needs the name a student would give it"


def test_the_folder_holds_more_than_submissions():
    """Two essays is not a folder. The assignment prompt must be recognised and not scored, and a
    document with nothing to match on must reach the stuck queue rather than being guessed at."""
    names = [p["filename"].lower() for p in seed_demo.load()["papers"].values()]
    assert any("prompt" in n for n in names), "no assignment in the folder"
    assert any("untitled" in n for n in names), "no unresolvable file in the folder"


def test_the_purge_is_scoped_to_one_run():
    src = inspect.getsource(seed_demo)
    assert "run_id = :run" in src
    assert "LIKE" not in src, "a name match is what scoping by the run was supposed to remove"
    assert "WHERE 1=1" not in src


def test_the_purge_deletes_every_table_that_references_an_artifact():
    """Derived from the models, not from the purge list — which is the point.

    `artifact_composition` arrived in migration 0017 and nobody updated `purge()`. The next purge
    failed on a foreign key with two papers already scored, and no test could have caught it,
    because both sides of the omission were the same omission. This reads the FKs and asks the
    purge whether it knows about each one.
    """
    from app.models import Base
    import scoring.models  # noqa: F401

    referencing = sorted(
        t.name for t in Base.metadata.tables.values()
        for fk in t.foreign_keys if fk.column.table.name == "artifact")
    assert referencing, "no table references artifact — the derivation has stopped working"

    listed = {t for t, _ in seed_demo._PURGE_ORDER}
    missing = [t for t in referencing if t not in listed]
    assert not missing, (
        f"tables referencing artifact that the purge does not delete: {missing}. The DELETE on "
        f"artifact will fail on a foreign key.")


def test_the_purge_deletes_children_before_the_parent():
    order = [t for t, _ in seed_demo._PURGE_ORDER]
    assert order[-1] == "artifact", "the parent has to go last"


def test_every_append_only_table_has_its_trigger_taken_off_and_put_back():
    """A cleanup script that left either table mutable would be a silent hole in the record's
    central invariant."""
    src = inspect.getsource(seed_demo.purge)
    tables = {t for t, _ in seed_demo._APPEND_ONLY}
    assert tables == {"score_event", "artifact_composition"}
    assert src.index("DISABLE TRIGGER") < src.index("ENABLE TRIGGER")


def test_the_trigger_restore_does_not_rely_on_a_finally():
    """ALTER TABLE is transactional in Postgres, so a failure rolls the DISABLE back with
    everything else. The finally that used to be here could not run — the transaction was already
    aborted — so it raised InFailedSqlTransaction on top of the real error and buried it."""
    assert "finally:" not in inspect.getsource(seed_demo.purge)


# ------------------------------------------------------------------ the fixture is scorable


def _criteria():
    out = []
    for node in registry_seed.load()["nodes"]:
        nid = registry_seed.trait_id(node["id"])
        cats = sorted(float(k) if "." in k else int(k) for k in node["levels"])
        out.append(Criterion(node_id=nid, criterion_label=node["name"], categories=cats,
                             descriptors=node["levels"], node_version_id=f"{nid}-v1"))
    return out


@pytest.mark.parametrize("c", _criteria(), ids=lambda c: c.node_id)
def test_every_fixture_node_renders_its_whole_scale(c):
    """render_scale raises on a missing descriptor. Better to learn that here than four minutes
    into a run that has already paid for half its calls."""
    out = render_scale(c.criterion_label, c.descriptors, c.categories)
    for cat in c.categories:
        assert f"Level {cat}:" in out


def test_a_fixture_paper_assembles_a_stage_c_prompt():
    paper = next(iter(seed_demo.load()["papers"].values()))
    prompt = build_evidence_prompt(_criteria()[0], paper["text"])
    assert "<text>" in prompt and paper["text"][:40] in prompt
    assert prompt.count("CRITERION: ") == 1


def test_the_papers_are_long_enough_to_be_attempts():
    for key, paper in seed_demo.load()["papers"].items():
        assert len(paper["text"]) > 200, f"{key} would be a strange thing to demonstrate with"
