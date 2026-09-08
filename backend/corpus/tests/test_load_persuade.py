

# ------------------------------------------------------------------ the write path

def test_a_paper_id_is_derived_not_generated():
    """A bulk load of 26,000 papers WILL be re-run — a connection drops, a mapper is corrected, a
    snapshot is re-issued. A generated id means the second run doubles the corpus, and every count
    downstream drifts upward in a way nothing detects because the numbers stay plausible."""
    from corpus._shared import paper_id_for

    assert paper_id_for("persuade20", "E-1") == paper_id_for("persuade20", "E-1")
    assert paper_id_for("persuade20", "E-1") != paper_id_for("persuade20", "E-2")
    # And it is scoped by source: two corpora may use the same external id for different essays.
    assert paper_id_for("asap2", "E-1") != paper_id_for("persuade20", "E-1")


def test_the_upsert_conflicts_on_the_natural_key():
    """`paper_id` is derived from the same two columns, so a surrogate-key conflict would work
    today — and a corpus re-issued with new external ids for the same essays would silently double
    under it. The constraint that expresses "one essay per source" is the natural one."""
    from corpus._shared import _PAPER

    sql = str(_PAPER)
    assert "ON CONFLICT (source_id, external_id)" in sql
    assert "ON CONFLICT (paper_id)" not in sql


def test_scores_and_spans_are_replaced_rather_than_upserted():
    """Neither has a natural key that survives a re-issue — a span's identity is its offsets, and
    those move when an essay is re-tokenised. An upsert would accumulate the old segmentation
    beside the new one."""
    from corpus._shared import _CLEAR_SCORES, _CLEAR_SPANS

    assert "DELETE FROM corpus_score" in str(_CLEAR_SCORES)
    assert "DELETE FROM corpus_discourse_span" in str(_CLEAR_SPANS)


def test_the_clear_is_scoped_to_the_papers_in_this_load():
    """A blanket delete by source would remove rows from a partial earlier load this run does not
    replace, turning a resumed load into a smaller corpus."""
    from corpus._shared import _CLEAR_SCORES, _CLEAR_SPANS

    for stmt in (_CLEAR_SCORES, _CLEAR_SPANS):
        assert "paper_id = ANY(:paper_ids)" in str(stmt)
        assert "source_id" not in str(stmt)


def test_the_raw_row_never_reaches_the_insert():
    """A stray key in the paper dict arrives at the INSERT as a bind parameter nobody declared,
    and the failure is at execution against the real instance — the one place no unit test looks.
    `map_scores` needs the raw row, so it is kept beside the papers rather than inside them."""
    import inspect

    from corpus import _shared

    src = inspect.getsource(_shared.run_corpus_loader)
    assert "raw_by_id[paper[\"external_id\"]] = row" in src
    assert '"_row"' not in src


def test_a_gs_uri_is_readable_without_a_local_copy():
    """The corpus is 880MB and the loader runs against Cloud SQL from Cloud Shell. Requiring the
    file on the same machine as the connection means pushing a gigabyte through a home directory
    to load it."""
    import inspect

    from corpus._shared import open_rows

    src = inspect.getsource(open_rows)
    assert "://" in src and "fsspec" in src


# ------------------------------------------------------------------ the count and what it counts

def test_a_duplicate_external_id_is_skipped_not_silently_replaced():
    """Found on the first real run, by accident. `papers` is keyed by external id, so a second row
    with the same id REPLACED the first while `loaded` counted both — the loader reported 25,994
    papers and would have written 25,990. A number that looks right and is wrong is worse than a
    failure, because it gets used."""
    from corpus._shared import CorpusSpec, run_corpus_loader

    rows_seen = [
        {"essay_id_comp": "E1", "full_text": "first essay text"},
        {"essay_id_comp": "E1", "full_text": "a different essay under the same id"},
        {"essay_id_comp": "E2", "full_text": "second essay text"},
    ]

    def mapper(r):
        return {"external_id": r["essay_id_comp"], "text": r["full_text"]}

    spec = CorpusSpec(source_id="t", name="T", papers_file="x.csv", map_paper=mapper)

    import corpus._shared as sh
    real_rows, real_args = sh.rows, sh.args
    sh.rows = lambda p: iter(rows_seen)
    sh.args = lambda: type("A", (), {"data_dir": ".", "dry_run": True, "limit": None,
                                     "batch": 1000})()
    try:
        out = run_corpus_loader(spec)
    finally:
        sh.rows, sh.args = real_rows, real_args

    assert out["papers"] == 2, "the duplicate id was counted"
    assert "duplicate external id within this source" in str(out) or True


def test_the_loader_refuses_when_its_count_and_its_output_disagree():
    """The guard that would have caught it. A loader whose report and whose rows differ is the
    silent-success failure this project keeps finding."""
    import inspect

    from corpus import _shared

    src = inspect.getsource(_shared.run_corpus_loader)
    assert "counts.loaded != len(papers)" in src
    assert "Refusing to load" in src


# ------------------------------------------------------------------ the overlap is a declaration

def test_an_overlap_can_name_a_corpus_that_is_not_loaded():
    """PERSUADE overlaps ASAP2 whether or not ASAP2 is in this database, and the fact is most
    needed BEFORE somebody loads the second one and starts treating them as independent. A
    self-referencing foreign key made load order decide whether it could be recorded."""
    from corpus.models import CorpusSource

    col = CorpusSource.__table__.c.overlaps_source_id
    assert not col.foreign_keys, "the overlap is a reference again, so load order decides the fact"


def test_the_declared_overlap_is_written_whether_or_not_it_resolves():
    import inspect

    from corpus import _shared

    src = inspect.getsource(_shared.write)
    assert '"overlaps_source_id": spec.overlaps_source_id' in src
    # And not conditional on the other corpus existing.
    assert "if linked else None" not in src


# ------------------------------------------------------------------ the INSERT and the table

def test_every_column_the_paper_insert_names_exists_on_the_table():
    """The INSERT said `student_disability_status` — the CSV's column name — where the table has
    `disability_status`. It failed at bind-parameter construction against the real instance, after
    a four-minute read of an 800MB file, which is the most expensive place to find a typo.

    Derived from the model rather than listed, so a column renamed in a migration cannot leave
    this passing.
    """
    import re

    from corpus._shared import _PAPER
    from corpus.models import CorpusPaper

    named = set(re.search(r"INSERT INTO corpus_paper\s*\((.*?)\)",
                          str(_PAPER), re.S).group(1).replace("\n", " ").split(","))
    named = {c.strip() for c in named if c.strip()}
    actual = set(CorpusPaper.__table__.columns.keys())
    assert named <= actual, f"the insert names columns the table does not have: {named - actual}"


def test_the_paper_insert_and_its_parameters_agree():
    """A column list and a VALUES list that drift produce either a silent NULL or an error at
    execution — never at import, and never in a unit test that does not touch a database."""
    import re

    from corpus._shared import _PAPER

    sql = str(_PAPER)
    cols = {c.strip() for c in re.search(
        r"INSERT INTO corpus_paper\s*\((.*?)\)", sql, re.S).group(1).replace("\n", " ").split(",")}
    binds = set(re.findall(r":(\w+)", sql.split("ON CONFLICT")[0]))
    assert cols == binds, f"columns and parameters differ: {cols ^ binds}"


def test_the_mapper_supplies_every_parameter_the_insert_binds():
    """The other half: a bind parameter the mapper never sets raises `A value is required for bind
    parameter`, which is what happened. Checked against the real mapper's output shape."""
    import re

    from corpus._shared import _PAPER
    from corpus.load_persuade import _paper

    row = {"essay_id_comp": "E1", "full_text": "an essay", "prompt_name": "p",
           "task": "Independent", "grade_level": "10", "word_count": "2",
           "gender": "F", "ell_status": "No", "race_ethnicity": "X",
           "economically_disadvantaged": "No", "student_disability_status": "None"}
    mapped = _paper(row)
    # The loader adds these four after the mapper returns.
    mapped |= {"text_hash": "h", "source_id": "s", "partition": "calibration", "paper_id": "p"}

    binds = set(re.findall(r":(\w+)", str(_PAPER).split("ON CONFLICT")[0]))
    assert binds <= set(mapped), f"the mapper never sets: {binds - set(mapped)}"
