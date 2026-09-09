"""The driver's assembly — the facet stamp, the idempotency key, and where an artifact goes next.

Everything here is a pure function of its arguments, which is the reason those functions exist
separately from the loop that calls them: the parts of the driver that are easy to get wrong are
the parts that assemble a row, and they should not need a database to check.

The parts that DO need one — the trigger, the append-only rule, the release authority — are proven
against real Postgres by `sql/20_scoring_smoketest.sql`, because a trigger created without error
says nothing about whether it fires.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.vocab import SCORE_STATUS_IDS
from scoring.escalate import Policy
from scoring.prompts import fingerprint
from scoring.rater import STAGES, RaterIdentity
from scoring.run_scoring import (AlreadyRunning, ConfigurationError, check_configuration,
                                 enters_calibration, event_rows, idempotency_key, next_state,
                                 score_pending, trait_set_version)
from scoring.score import Outcome

# The resolved default policy. Part of the rater identity, because the harness — models,
# prompts, normalisation, and how deep it may look — IS the rater.
DEFAULT_ESCALATION = Policy().as_dict()

ARTIFACT = {
    "artifact_id": "art-1", "run_id": "run-9", "student_id": "stu-1", "section_id": "sec-1",
    "task_id": "task-1", "iteration": "final", "window_label": "fall 2026",
    "content_hash": "h", "source_uri": None, "tenant_id": "public", "visibility": "public",
}

IDENTITY = RaterIdentity("cfg-1", "claude-opus-5", "high", fingerprint(), "1",
                         DEFAULT_ESCALATION)


def outcome(status="scored", level=3.0, node="n1"):
    return Outcome(node_id=node, node_version_id=f"{node}-v2", status=status, level=level,
                   confidence="high", reason="r", evidence={"proposed": 1, "kept": [],
                                                            "dropped": [], "norm_version": "1"})


# ------------------------------------------------------------------ idempotency


def test_the_idempotency_key_does_not_contain_the_run_id():
    """A resumed run is the same run doing the same work. Keying on the run id would make every
    retry a fresh observation — a measurement bug wearing a throughput bug's clothes."""
    key = idempotency_key("art-1", "n1", "cfg-1", 1)
    assert "run-9" not in key
    assert key == idempotency_key("art-1", "n1", "cfg-1", 1)


def test_the_key_separates_the_things_that_are_genuinely_different_observations():
    base = idempotency_key("art-1", "n1", "cfg-1", 1)
    assert base != idempotency_key("art-2", "n1", "cfg-1", 1)   # different text
    assert base != idempotency_key("art-1", "n2", "cfg-1", 1)   # different item
    assert base != idempotency_key("art-1", "n1", "cfg-2", 1)   # different rater
    assert base != idempotency_key("art-1", "n1", "cfg-1", 2)   # escalated pass


# ------------------------------------------------------------------ the trait set stamp


def test_the_trait_set_version_is_order_sensitive():
    """A different order is a different administration — the traits were presented differently."""
    assert trait_set_version(["a", "b"]) != trait_set_version(["b", "a"])
    assert trait_set_version(["a", "b"]) == trait_set_version(["a", "b"])


def test_the_trait_set_version_changes_when_a_wording_changes():
    assert trait_set_version(["n1-v1", "n2-v1"]) != trait_set_version(["n1-v2", "n2-v1"])


# ------------------------------------------------------------------ calibration membership


def test_only_a_scored_outcome_on_a_measurement_occasion_is_proposed_for_calibration():
    assert enters_calibration(outcome("scored"), True) is True
    assert enters_calibration(outcome("abstained", None), True) is False
    assert enters_calibration(outcome("no_verified_evidence", None), True) is False


def test_a_draft_never_enters_calibration():
    """Drafts are low stakes for the student and mistakes there are useful. Letting them move the
    parameters drives revision at the stage where exploration is the point."""
    assert enters_calibration(outcome("scored"), False) is False


# ------------------------------------------------------------------ the row


def test_every_status_written_is_in_cores_vocabulary():
    rows = event_rows(ARTIFACT, [outcome("scored"), outcome("abstained", None, "n2")],
                      IDENTITY, "ts-x", True)
    assert all(r["status"] in SCORE_STATUS_IDS for r in rows)


def test_a_status_outside_the_vocabulary_is_refused_here_rather_than_by_the_database():
    with pytest.raises(ValueError, match="SCORE_STATUSES"):
        event_rows(ARTIFACT, [outcome("pretty_good")], IDENTITY, "ts-x", True)


def test_a_level_exists_if_and_only_if_the_status_is_scored():
    """The same rule the CHECK constraint enforces. Asserted here too because a row that reaches
    the database and is rejected has already cost a model call."""
    rows = event_rows(ARTIFACT, [outcome("scored"), outcome("abstained", None, "n2"),
                                 outcome("not_scorable", None, "n3")], IDENTITY, "ts-x", True)
    for r in rows:
        assert (r["level"] is not None) == (r["status"] == "scored")


def test_the_form_variant_stays_a_separate_column_and_stays_empty():
    """There are no alternate forms yet. Folding one into rubric_version later would make its
    effect unrecoverable — the hidden-facet failure the construct audit found in the existing
    rubric data, and the reason this column exists before anything fills it."""
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    assert r["form_variant"] is None
    assert r["rubric_version"] == "n1-v2"


def test_a_machine_rater_is_its_configuration_and_has_no_individual_identity():
    """A human is identified individually because rater severity cannot be estimated from an
    anonymous pool. A machine has no individual — the configuration IS the rater."""
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    assert r["scorer_type"] == "ai"
    assert r["scorer_id"] is None
    assert r["scoring_configuration_id"] == "cfg-1"
    assert r["human_blind"] is None


def test_the_binding_is_denormalised_onto_every_event():
    """The event is self-describing: a score that needs a join to say whose it is stops being
    readable the moment the artifact row is touched."""
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    for field in ("student_id", "section_id", "task_id", "iteration", "window_label", "run_id"):
        assert r[field] == ARTIFACT[field]


def test_every_event_gets_its_own_id():
    rows = event_rows(ARTIFACT, [outcome(node="n1"), outcome(node="n2")], IDENTITY, "ts-x", True)
    assert rows[0]["event_id"] != rows[1]["event_id"]
    assert rows[0]["idempotency_key"] != rows[1]["idempotency_key"]


def test_the_evidence_is_serialised_as_json_for_the_jsonb_column():
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    assert isinstance(r["evidence"], str) and r["evidence"].startswith("{")


# ------------------------------------------------------------------ where it goes next


def test_a_fully_unscorable_artifact_goes_to_not_scorable():
    state, reason = next_state([outcome("not_scorable", None, "n1"),
                                outcome("not_scorable", None, "n2")])
    assert state == "not_scorable"


def test_abstentions_still_leave_the_artifact_scored():
    """`scored` means every criterion has an outcome, including abstentions. Holding the artifact
    back because one criterion needs a human would stall the eleven that do not."""
    state, _ = next_state([outcome("scored"), outcome("abstained", None, "n2"),
                           outcome("no_verified_evidence", None, "n3")])
    assert state == "scored"


def test_a_mixture_of_not_scorable_and_scored_is_loud():
    """not_scorable is a fact about the artifact, not about a criterion. It cannot happen today;
    if it ever does, rounding to whichever is more common would bury the cause."""
    with pytest.raises(ValueError, match="not_scorable is a fact about the artifact"):
        next_state([outcome("scored"), outcome("not_scorable", None, "n2")])


# ------------------------------------------------------------------ the configuration gate


def test_a_configuration_whose_prompts_have_moved_is_refused():
    stale = RaterIdentity("cfg-old", "claude-opus-5", "high",
                          {"evidence": {"version": "ev.1", "sha256": "0000000000000000"},
                           "score": {"version": "sc.1", "sha256": "1111111111111111"}}, "1",
                          DEFAULT_ESCALATION)
    with pytest.raises(ConfigurationError, match="not the one that was promoted"):
        check_configuration(stale)


def test_a_configuration_that_matches_the_text_on_disk_passes():
    check_configuration(IDENTITY)


def test_a_floating_model_alias_is_not_a_pinned_rater():
    """An alias that resolves to a new build changes the rater without changing the record, and
    every score before and after looks identical."""
    with pytest.raises(ValueError, match="floating alias"):
        RaterIdentity("cfg-x", "claude-opus-latest", "high", fingerprint(), "1",
                      DEFAULT_ESCALATION)


# ------------------------------------------------------------------ the SQL itself


def test_no_optional_parameter_is_compared_to_null_without_a_type():
    """`AND (:run_id IS NULL OR run_id = :run_id)` looks obviously fine and Postgres refuses it.

    A bind parameter that only ever appears beside IS NULL gives the planner nothing to infer a
    type from, and the whole statement fails with `could not determine data type of parameter $2`
    — at execution, against a real server. Every unit test here passed; the first Cloud Shell run
    did not survive its first query.

    This is a text scan rather than a real check, and it only catches the shape that already bit
    us. That is the honest scope of it: the general problem needs a database, and this is the part
    that can be caught without one.
    """
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("run_scoring.py").read_text(
        encoding="utf8")
    bare = [m.group(0) for m in re.finditer(r"(?<!AS text\)\s)\B:(\w+)\s+IS\s+NULL", src)]
    assert not bare, (
        f"optional bind parameters compared to NULL without a CAST: {bare}. Postgres cannot infer "
        f"a type for them and refuses the statement.")


# --------------------------------------------------------------------------- #
# A reference paper's text is a column, not a file.
#
# The first corpus scoring run failed with `No such file or directory:
# corpus:persuade20:0EC4EF416F2F` — `source_uri` on a reference paper is a corpus locator, not a
# path, and `read_text` fell through to the file branch. Loud, and free: it happened before any
# model call.
# --------------------------------------------------------------------------- #

def test_corpus_text_is_preferred_over_the_file_branch():
    from scoring.run_scoring import read_text

    assert read_text({"artifact_id": "a", "corpus_text": "the essay",
                      "source_uri": "corpus:persuade20:E1"}) == "the essay"


def test_intake_text_still_wins_for_a_student_paper():
    """A student paper and a reference paper can never both be present, but the order has to be
    deliberate rather than incidental."""
    from scoring.run_scoring import read_text

    assert read_text({"artifact_id": "a", "intake_text": "handed in",
                      "corpus_text": "reference"}) == "handed in"


def test_a_corpus_locator_is_never_opened_as_a_path():
    """The failure mode, pinned. Without the corpus branch this raises NotImplementedError or
    FileNotFoundError depending on the locator's shape — both after the artifact was bound and
    before anything was scored."""
    import pytest

    from scoring.run_scoring import read_text

    with pytest.raises((NotImplementedError, FileNotFoundError, OSError)):
        read_text({"artifact_id": "a", "source_uri": "corpus:persuade20:E1"})


def test_the_corpus_join_is_scoped_to_the_corpus_tenant():
    """`bind_corpus` writes the paper id into `student_id`. Joining without the tenant predicate
    would let a real student id collide with a corpus paper id and silently score a student's
    paper against a stranger's text."""
    from scoring.run_scoring import _PENDING

    sql = str(_PENDING)
    assert "LEFT JOIN corpus_paper" in sql
    assert "a.tenant_id = 'corpus'" in sql
    assert "cp.paper_id = a.student_id" in sql


def test_scoring_reads_the_corpus_table_rather_than_importing_it():
    """Modules integrate through produced tables. `scoring` may not import `corpus`, and the
    boundary test enforces it — this says the same thing about the read path specifically."""
    import ast
    import pathlib

    from scoring import run_scoring

    tree = ast.parse(pathlib.Path(run_scoring.__file__).read_text(encoding="utf8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert "corpus" not in imported


# ------------------------------------------------------------------ one scorer per tenant

class _Result:
    def __init__(self, value=None, rows=()):
        self._value, self._rows = value, rows

    def scalar(self):
        return self._value

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _Conn:
    """Records every statement, answers the lock with whatever the engine was told to say."""

    def __init__(self, eng):
        self.eng = eng

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.eng.statements.append(sql)
        if "pg_try_advisory_lock" in sql:
            return _Result(self.eng.lock_granted)
        return _Result(rows=self.eng.pending)

    def close(self):
        self.eng.closed += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _Engine:
    def __init__(self, *, lock_granted=True, pending=()):
        self.lock_granted, self.pending = lock_granted, list(pending)
        self.statements, self.closed = [], 0

    def connect(self):
        return _Conn(self)


@pytest.fixture
def fake_engine(monkeypatch):
    def install(**kw):
        eng = _Engine(**kw)
        monkeypatch.setattr("scoring.run_scoring.engine", lambda: eng)
        return eng
    return install


def test_a_second_scorer_on_the_same_tenant_is_refused(fake_engine):
    """The money is the reason. `_PENDING` selects artifacts in `bound`, and an artifact stays
    `bound` until its last trait lands — so two scorers minutes apart select the SAME papers and
    both pay for them. The unique constraint on `idempotency_key` blocks the duplicate row, and it
    blocks it after the call has been billed."""
    fake_engine(lock_granted=False)
    with pytest.raises(AlreadyRunning):
        score_pending(tenant="corpus", config_key="writing-default")


def test_the_refusal_names_the_tenant_and_where_to_look(fake_engine):
    """It fires at 1am when somebody has forgotten a shell is still running. A bare exception
    class sends them to read this file."""
    fake_engine(lock_granted=False)
    with pytest.raises(AlreadyRunning) as e:
        score_pending(tenant="corpus", config_key="writing-default")
    assert "corpus" in str(e.value)
    assert "pg_locks" in str(e.value)


def test_the_lock_is_released_even_when_it_was_never_acquired(fake_engine):
    """The refusal path closes its connection too. Leaking one per refusal would exhaust the pool
    on a job that retries."""
    eng = fake_engine(lock_granted=False)
    with pytest.raises(AlreadyRunning):
        score_pending(tenant="corpus", config_key="writing-default")
    assert eng.closed >= 1


def test_the_lock_connection_outlives_the_query_that_selects_the_batch(fake_engine):
    """A session-level advisory lock dies with its session. Taking it on the connection that reads
    `_PENDING` — which is opened and closed in a `with` — would release it before the first paper
    was scored, and the guard would be decorative."""
    eng = fake_engine(lock_granted=True, pending=())
    score_pending(tenant="corpus", config_key="writing-default")
    lock_at = next(i for i, s in enumerate(eng.statements) if "pg_try_advisory_lock" in s)
    pending_at = next(i for i, s in enumerate(eng.statements) if "FROM artifact" in s)
    assert lock_at < pending_at
    # Two connections: the one holding the lock, and the one that read the batch.
    assert eng.closed == 2


def test_the_lock_is_per_tenant_not_global(fake_engine):
    """Corpus scoring and a district's scoring are unrelated work on disjoint artifacts. One
    global lock would make a two-hour anchor run block a teacher's papers."""
    eng = fake_engine(lock_granted=True)
    score_pending(tenant="corpus", config_key="writing-default")
    lock = next(s for s in eng.statements if "pg_try_advisory_lock" in s)
    assert "hashtext(:tenant)" in lock


# ------------------------------------------------------------------ a model per stage

def _ident(**over):
    base = dict(config_id="cfg-1", model_id="claude-opus-5", effort="high",
                prompt_versions=fingerprint(), normalization_version="1",
                escalation=DEFAULT_ESCALATION)
    return RaterIdentity(**(base | over))


def test_a_stage_with_no_override_uses_the_base_model():
    assert _ident().models == {s: "claude-opus-5" for s in STAGES}


def test_an_override_applies_to_its_stage_and_no_other():
    """Span proposal is verified against the paper, so a weaker model there costs verified spans
    and routes to abstention. Level assignment is checked by nothing. Different risks, and the
    override has to be able to tell them apart."""
    i = _ident(stage_models={"evidence": "claude-haiku-4-5-20251001"})
    assert i.models["evidence"] == "claude-haiku-4-5-20251001"
    assert i.models["score"] == "claude-opus-5"
    assert i.models["fit"] == "claude-opus-5"


def test_declaring_no_overrides_and_declaring_the_same_model_everywhere_collide():
    """What is hashed is what the rater DOES, not how verbosely it was written down. Splitting one
    rater into two over notation would break the connectivity that puts them on one scale."""
    assert _ident().definition_hash == _ident(
        stage_models={s: "claude-opus-5" for s in STAGES}).definition_hash


def test_a_different_model_at_one_stage_is_a_different_rater():
    assert _ident().definition_hash != _ident(
        stage_models={"evidence": "claude-haiku-4-5-20251001"}).definition_hash


def test_a_floating_alias_in_an_override_is_refused_too():
    """The guard checked `model_id` only. An override is exactly as capable of being an alias that
    silently resolves to a new build, and it is the one nobody would think to look at."""
    with pytest.raises(ValueError, match="floating alias"):
        _ident(stage_models={"evidence": "claude-haiku-latest"})


def test_a_model_assigned_to_a_stage_that_does_not_exist_is_refused():
    """Otherwise it is a model nobody calls, and nothing would say so — the configuration would
    look like a mixed harness and behave like a single-model one."""
    with pytest.raises(ValueError, match="unknown scoring stage"):
        _ident(stage_models={"evidenc": "claude-haiku-4-5-20251001"})


class _RecordingClient:
    """Stands in for the Anthropic client and records which model each stage asked for."""

    class _Messages:
        def __init__(self, seen):
            self.seen = seen

        def create(self, *, model, **kw):
            self.seen.append(model)
            import types
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text='{"spans": []}')],
                usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

    def __init__(self):
        self.seen = []
        self.messages = self._Messages(self.seen)


def test_each_stage_actually_calls_its_own_model():
    """The property that matters, and the one the resolution alone does not prove: a correct
    `models` map still sends every call to `model_id` if `_call` never reads it."""
    from scoring.rater import AnthropicRater

    rater = AnthropicRater(_ident(stage_models={"evidence": "claude-haiku-4-5-20251001"}),
                           api_key="not-used")
    # The client is thread-local now, so the stand-in goes where this thread looks for it.
    rater._local.client = _RecordingClient()
    rater.propose_spans("p")
    rater.assign_level("p")
    assert rater._local.client.seen == ["claude-haiku-4-5-20251001", "claude-opus-5"]


# ------------------------------------------------------------------ the stage-D method

def test_the_method_is_part_of_the_rater():
    """The largest difference between two raters this system can express — larger than a model
    change. Two configurations differing only in it produce entirely different bodies of scores,
    so MFRM has to hold them apart rather than average them together."""
    cat = _ident(prompt_versions=fingerprint("category"))
    cum = _ident(prompt_versions=fingerprint("cumulative"), level_method="cumulative")
    assert cat.definition_hash != cum.definition_hash


def test_the_threshold_is_part_of_it_even_under_the_category_method():
    """A rater is its parameters. A hash that drops a field because the current method ignores it
    stops describing the rater the moment the method changes."""
    assert _ident(level_threshold=0.5).definition_hash != \
           _ident(level_threshold=0.6).definition_hash


def test_a_method_nobody_implemented_is_refused():
    with pytest.raises(ValueError, match="unknown level_method"):
        _ident(level_method="vibes")


def test_a_threshold_at_the_ends_is_refused():
    """At 0 every band clears and every paper is a 6; at 1 none does and every paper is a 1. Both
    score without judging."""
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="not a probability"):
            _ident(level_threshold=bad)


def test_each_method_fingerprints_only_the_stage_d_prompt_it_uses():
    """A cumulative rater never sends the category prompt and vice versa. Fingerprinting both
    would make every existing configuration stop matching itself the moment the other prompt was
    added — and would claim a rater was promoted against text it never saw."""
    assert set(fingerprint("category")) == {"fit", "evidence", "score"}
    assert set(fingerprint("cumulative")) == {"fit", "evidence", "band"}


def test_a_cumulative_configuration_passes_its_own_prompt_check():
    check_configuration(_ident(prompt_versions=fingerprint("cumulative"),
                               level_method="cumulative"))


def test_a_configuration_stamped_for_the_other_method_is_refused():
    """The check compares against the prompts THIS rater uses, so a configuration promoted as
    `category` and then switched to `cumulative` in place no longer matches itself."""
    with pytest.raises(ConfigurationError, match="not the one that was promoted"):
        check_configuration(_ident(prompt_versions=fingerprint("category"),
                                   level_method="cumulative"))


def test_each_thread_gets_its_own_api_client():
    """Sharing one client across the scoring pools produced `400 Invalid request data` on roughly
    one call in six under concurrency. Reproduced with an IDENTICAL prompt: six sequential calls
    all succeeded, six concurrent ones did not — so the request was never the problem, and an
    evening of the failure looking data-shaped came from that.

    It surfaced only with the cumulative method, which nests two pools (criteria, and the bands
    within each) for up to nineteen calls in flight per paper instead of eight. The category wave
    ran clean at the lower number, which is the worst way for a race to behave: absent right up
    until the load that matters.
    """
    import threading

    from scoring.rater import AnthropicRater

    rater = AnthropicRater(_ident(), api_key="not-used")
    seen: dict[int, int] = {}

    def grab(n):
        seen[n] = id(rater._client)

    threads = [threading.Thread(target=grab, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(seen.values())) == 4, "threads shared a client"
    assert id(rater._client) == id(rater._client), "a thread must reuse its own client"


# ------------------------------------------------------------------ the gate reaches corpus papers

def test_the_pending_query_carries_the_corpus_assignment_and_source():
    """`fit.check` short-circuits without a task statement, so a corpus paper skipped stage B
    while student work did not — the anchor severity described a rater running one stage fewer
    than the one in production. Both columns existed in the file from the first load and were
    read by nothing."""
    from scoring.run_scoring import _PENDING

    sql = str(_PENDING)
    assert "cp.assignment AS corpus_assignment" in sql
    assert "cp.source_text AS corpus_source_text" in sql


def test_a_corpus_assignment_is_preferred_over_an_intake_lookup():
    """A corpus paper's task is a column because the corpus states it; a student's is a file the
    intake classified. Reaching for the file first would spend a query per artifact to find
    nothing, and then fall back anyway."""
    import inspect

    from scoring.run_scoring import _score_one

    src = inspect.getsource(_score_one)
    i = src.index("task_statement =")
    stanza = src[i:i + 400]
    assert stanza.index("corpus_assignment") < stanza.index("_TASK_STATEMENT")
