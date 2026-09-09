"""PERSUADE 2.0 -> corpus tables.

    python -m corpus.load_persuade --data-dir ~ --dry-run

Two files, and which one supplies what is the whole point.

PAPERS from `persuade_2.0_human_scores_demo_id_github.csv`: all 25,990 essays, one holistic score
each, the demographics, the assignment and the source text.

SPANS from `persuade_corpus_2.0_train.csv`: the discourse segmentation AND
`discourse_effectiveness`, the human rating of each element as Ineffective, Adequate or Effective.
This is what the 2021 file (`persuade_corpus_1.0.csv`) never had, and its absence is why eight of
the ten traits this system scores reported `no pairs` on 334 papers scored twice.

## The segmentation ships in two splits, and BOTH are needed

Measured: train has 173,266 rows over 15,594 essays; test has 112,117 rows over 10,402. They
overlap on zero essays and their union is 25,996 — the corpus holds 25,990. Together they cover it;
either alone leaves a hole, and the train split alone would have given an element comparator to
60% of the papers while reporting nothing amiss.

Neither is used as the PAPERS file. Both carry `full_text` and `holistic_essay_score`, so either
would load as papers and quietly shrink the corpus to its own split — the loader would say it
loaded exactly what it was given.

The train/test names are the competition's, not ours. Nothing here trains on anything; this
system's own calibration/validation split is derived by hash in `partition_for` and is unrelated.

## Column names moved between the files

`word_count` in the essays file is `essay_word_count` in the 2.0 file. Both are read, because a
mapper that silently gets None from a renamed column is exactly how this loader once wrote 25,994
papers into 25,990 rows.
"""
from __future__ import annotations

from ._shared import CorpusSpec, blank_to_none, run_corpus_loader


def _int(raw):
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else None


def _paper(row):
    text = (row.get("full_text") or "").strip()
    if not text:
        return None
    return {
        "external_id": row["essay_id_comp"],
        "text": text,
        "prompt_name": blank_to_none(row.get("prompt_name")),
        "task_type": blank_to_none(row.get("task")),
        "grade_level": blank_to_none(row.get("grade_level")),
        # Either name. The 2021 file said `word_count`; the 2.0 file says `essay_word_count`.
        # A mapper that silently reads None from a renamed column is how this loader once counted
        # 25,994 papers into 25,990 rows.
        "word_count": _int(row.get("word_count") or row.get("essay_word_count")),
        # Blank stays NULL: absence of a label is not a label, and letting it become one would
        # quietly create an "unknown" subgroup in every fairness table.
        "gender": blank_to_none(row.get("gender")),
        "ell_status": blank_to_none(row.get("ell_status")),
        "race_ethnicity": blank_to_none(row.get("race_ethnicity")),
        "economically_disadvantaged": blank_to_none(row.get("economically_disadvantaged")),
        "disability_status": blank_to_none(row.get("student_disability_status")),
        # THE TASK STATEMENT. Present in the file from the first load and not read, so corpus
        # papers reached the scorer with none — and `fit.check` short-circuits without one. The
        # anchor papers were therefore skipping a stage that every piece of student work goes
        # through, which makes the rater they characterise not quite the rater in production.
        "assignment": blank_to_none(row.get("assignment")),
        # THE SOURCE TEXT, for the text-dependent prompts. Also present and not read.
        #
        # This one is a validity problem rather than a fidelity one. The text-dependent evidence
        # trait is defined as evidence "taken from the source text(s)" — and nothing in this
        # pipeline has ever seen the source text, so the rater was being asked whether a
        # quotation came from a document it could not read.
        "source_text": blank_to_none(row.get("source_text")),
    }


def _scores(row, paper_id):
    raw = (row.get("holistic_essay_score") or "").strip()
    if not raw:
        return []
    # rater_id stays absent because the corpus has none. Recording that as a null rather than
    # inventing a synthetic rater is what keeps "severity is not estimable from this" visible.
    return [{"paper_id": paper_id, "kind": "holistic", "label": None,
             "value": float(raw), "scale_min": 1, "scale_max": 6, "rater_id": None}]


def _span(row):
    kind = (row.get("discourse_type") or "").strip()
    if not kind or kind == "Unannotated":
        return None
    return {
        "external_id": row["essay_id_comp"],
        "discourse_type": kind,
        "start_char": int(float(row["discourse_start"])) if row.get("discourse_start") else None,
        "end_char": int(float(row["discourse_end"])) if row.get("discourse_end") else None,
        "text": row.get("discourse_text"),
        # THE HUMAN RATING OF THIS ELEMENT: Ineffective, Adequate or Effective.
        #
        # NULL through every load before this one, because the 2021 segmentation file has no such
        # column — so eight of the ten traits this system scores had no comparator, and said so on
        # every report as `no pairs`.
        #
        # Kept as the corpus's own word rather than converted to 1/2/3 here. The ordering is a
        # decision belonging to whoever scores against it (`registry.persuade_rubrics` maps them),
        # and a number stored in this column would be that decision made invisibly, in the place
        # nobody would look for it.
        "effectiveness": blank_to_none(row.get("discourse_effectiveness")),
    }


SPEC = CorpusSpec(
    source_id="persuade20",
    name="PERSUADE 2.0",
    # PAPERS from the essays file, which has all 25,990. SPANS from the 2.0 train file, which has
    # the effectiveness ratings and only 15,594 essays. Using the 2.0 file for both would drop 40%
    # of the corpus without saying so.
    papers_file="persuade20/persuade_2.0_human_scores_demo_id_github.csv",
    spans_file=("persuade20/persuade_corpus_2.0_train.csv",
                "persuade20/persuade_corpus_2.0_test.csv"),
    url="https://github.com/scrosseye/persuade_corpus_2.0",
    snapshot="2026-09-09",
    overlaps_source_id="asap2",
    overlap_note=("ASAP2 shares 12,725 essays byte-identical at identical scores, and every ASAP "
                  "prompt is a PERSUADE prompt — they are not independent sources, so a "
                  "calibrate-on-one / validate-on-the-other split across them would be circular"),
    map_paper=_paper,
    map_scores=_scores,
    map_span=_span,
)

if __name__ == "__main__":
    run_corpus_loader(SPEC)
