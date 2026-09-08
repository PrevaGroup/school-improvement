

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
