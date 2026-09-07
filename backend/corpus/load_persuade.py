"""PERSUADE 2.0 -> corpus tables.

    python -m corpus.load_persuade --data-dir N:/studentworkfeedback/corpus --dry-run

Two files, one corpus: `persuade_2.0_human_scores_demo_id_github.csv` carries the essays, one
holistic score each, and the demographics; `persuade_corpus_1.0.csv` carries discourse-element
segmentation over the same essays. Neither carries a rater, and neither carries trait scores.
"""
from __future__ import annotations

from ._shared import CorpusSpec, blank_to_none, run_corpus_loader


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
        "word_count": int(row["word_count"]) if (row.get("word_count") or "").isdigit() else None,
        # Blank stays NULL: absence of a label is not a label, and letting it become one would
        # quietly create an "unknown" subgroup in every fairness table.
        "gender": blank_to_none(row.get("gender")),
        "ell_status": blank_to_none(row.get("ell_status")),
        "race_ethnicity": blank_to_none(row.get("race_ethnicity")),
        "economically_disadvantaged": blank_to_none(row.get("economically_disadvantaged")),
        "disability_status": blank_to_none(row.get("student_disability_status")),
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
        "effectiveness": None,   # not in this release; the column exists so its absence is visible
    }


SPEC = CorpusSpec(
    source_id="persuade20",
    name="PERSUADE 2.0",
    papers_file="persuade20/persuade_2.0_human_scores_demo_id_github.csv",
    spans_file="persuade20/persuade_corpus_1.0.csv",
    licence="CC BY 4.0",
    url="https://github.com/scrosseye/persuade_corpus_2.0",
    snapshot="2026-09-05",
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
