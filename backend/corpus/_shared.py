"""The shared runner every corpus loader calls. One spec plus this; the loaders stay thin.

Follows `public_metrics/_shared.py`: read from a local path or a gs:// URI, conform, upsert, and
print what was loaded, skipped and excluded. A loader that cannot say what it dropped is a loader
nobody can debug.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping

from sqlalchemy import text

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# Papers are split by a deterministic hash of source and external id, never by row order or by
# sampling at load time. Reproducibility is the point: the same corpus must produce the same
# holdout on a different machine, or "held out from calibration" is a claim nobody can check.
VALIDATION_SHARE = 0.20
_PARTITION_SALT = "corpus-partition-v1"


def partition_for(source_id: str, external_id: str,
                  share: float = VALIDATION_SHARE) -> str:
    """calibration | validation, decided by hash.

    Deliberately NOT random and NOT stratified. Stratifying on demographics would make the holdout
    depend on labels the fairness analysis is about to test, and a seeded shuffle would still make
    the split an artefact of load order.
    """
    h = hashlib.sha256(f"{_PARTITION_SALT}:{source_id}:{external_id}".encode()).hexdigest()
    return "validation" if (int(h[:8], 16) / 0xFFFFFFFF) < share else "calibration"


def text_hash(text: str) -> str:
    """Normalised hash, for detecting the same essay arriving from two sources — which is how the
    ASAP2/PERSUADE overlap was found, and how the next one will be."""
    return hashlib.md5(" ".join(text.split()).strip().lower().encode()).hexdigest()


@dataclass
class Counts:
    read: int = 0
    loaded: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def report(self, what: str) -> None:
        print(f"  {what}: read {self.read:,} · loaded {self.loaded:,}")
        for reason, n in sorted(self.skipped.items(), key=lambda kv: -kv[1]):
            print(f"      skipped {n:,} — {reason}")


@dataclass
class CorpusSpec:
    """What one loader needs to say. Everything else is shared."""
    source_id: str
    name: str
    papers_file: str
    url: str | None = None
    snapshot: str | None = None
    spans_file: str | None = None
    overlaps_source_id: str | None = None
    overlap_note: str | None = None
    # row -> a paper dict, or None to skip (with a reason recorded by the mapper)
    map_paper: Callable[[Mapping[str, str]], dict[str, Any] | None] = None
    map_scores: Callable[[Mapping[str, str], str], list[dict[str, Any]]] = None
    map_span: Callable[[Mapping[str, str]], dict[str, Any] | None] = None


# A stable namespace, so `paper_id` is a pure function of (source, external id). Re-running a
# load must produce the same ids or every re-run doubles the corpus and every score written
# against a paper points at a row that no longer exists.
_NS = uuid.UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")


def paper_id_for(source_id: str, external_id: str) -> str:
    return str(uuid.uuid5(_NS, f"corpus:{source_id}:{external_id}"))


def open_rows(path: str):
    """A local path or a gs:// URI.

    The corpus is 880MB and lives wherever it was downloaded; the loader runs against Cloud SQL
    from Cloud Shell. Requiring the file to be on the same machine as the database connection
    would mean pushing a gigabyte through a home directory to load it. `fsspec` is already a
    dependency and reads both, so the source is a URI rather than a path.
    """
    if "://" in path:
        import fsspec

        return fsspec.open(path, "rt", encoding="utf8", errors="replace", newline="").open()
    return open(path, encoding="utf8", errors="replace", newline="")


def rows(path: str) -> Iterator[dict[str, str]]:
    fh = open_rows(path)
    try:
        yield from csv.DictReader(fh)
    finally:
        fh.close()


def blank_to_none(v: str | None) -> str | None:
    """A blank demographic is NOT a label. Preserving it as NULL is what stops 'unknown' quietly
    becoming a subgroup in a fairness table."""
    v = (v or "").strip()
    return v or None


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=os.environ.get("CORPUS_DIR", "."))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--papers-only", action="store_true",
                   help="skip the span file. Adding a column to `corpus_paper` otherwise means "
                        "re-reading 800MB of segmentation to change nothing in it.")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--batch", type=int, default=1000,
                   help="rows per INSERT. 26,000 papers in one statement is a memory problem "
                        "on the client and a lock held for minutes on the server.")
    return p.parse_args()


def run_corpus_loader(spec: CorpusSpec) -> dict[str, Any]:
    """Read, conform, and report. Returns the summary so a test can assert on it without a database.

    Writing is intentionally not implemented here yet: the loaders run against Cloud SQL from Cloud
    Shell like every other bulk load in this repo, and a half-written insert path that nobody has
    run against the real instance is worse than none. What this does today is the conforming and
    the counting — which is the part with the decisions in it.
    """
    a = args()
    papers_path = os.path.join(a.data_dir, spec.papers_file)
    print(f"{spec.name} ({spec.source_id})")
    if spec.overlaps_source_id:
        print(f"  ! overlaps {spec.overlaps_source_id}: {spec.overlap_note}")

    counts, hashes, papers = Counts(), {}, {}
    raw_by_id: dict[str, Mapping[str, str]] = {}
    for i, row in enumerate(rows(papers_path)):
        if a.limit and i >= a.limit:
            break
        counts.read += 1
        paper = spec.map_paper(row)
        if paper is None:
            counts.skip("mapper rejected the row")
            continue
        if paper["external_id"] in papers:
            # Keyed by external id, so a second row with the same id would REPLACE the first and
            # `loaded` would count both. That is a loader reporting more rows than it wrote —
            # found when a foreign-key error dumped paper_count 25,990 beside "loaded 25,994".
            counts.skip("duplicate external id within this source")
            continue
        h = text_hash(paper["text"])
        if h in hashes:
            counts.skip("duplicate essay text within this source")
            continue
        hashes[h] = paper["external_id"]
        paper["text_hash"] = h
        paper["source_id"] = spec.source_id
        paper["partition"] = partition_for(spec.source_id, paper["external_id"])
        # Derived, never generated: re-running a load must produce the same ids, or the second run
        # doubles the corpus and every score written against a paper points at a row that is gone.
        paper["paper_id"] = paper_id_for(spec.source_id, paper["external_id"])
        # The raw row is kept OUT of the paper dict — it is not a column, and a stray key reaches
        # the INSERT as a bind parameter nobody declared.
        raw_by_id[paper["external_id"]] = row
        papers[paper["external_id"]] = paper
        counts.loaded += 1
    counts.report("papers")

    # The count and the thing counted, checked against each other. A loader whose report and whose
    # output disagree is worse than one that fails: the number looks right and is used.
    if counts.loaded != len(papers):
        raise RuntimeError(
            f"the loader counted {counts.loaded:,} papers and holds {len(papers):,}. Something "
            f"replaced a paper instead of skipping it, so the report overstates what would be "
            f"written. Refusing to load.")

    split = {"calibration": 0, "validation": 0}
    for p in papers.values():
        split[p["partition"]] += 1
    print(f"      partition: {split['calibration']:,} calibration / "
          f"{split['validation']:,} validation")

    spans, span_rows = Counts(), []
    if spec.spans_file and not a.papers_only:
        spans_path = os.path.join(a.data_dir, spec.spans_file)
        for i, row in enumerate(rows(spans_path)):
            if a.limit and i >= a.limit * 12:
                break
            spans.read += 1
            span = spec.map_span(row) if spec.map_span else None
            if span is None:
                spans.skip("mapper rejected the row")
            elif span["external_id"] not in papers:
                spans.skip("span for a paper not in this load")
            else:
                ext = span.pop("external_id")
                span["paper_id"] = papers[ext]["paper_id"]
                # A span has no natural key that survives a re-issue — its identity is its
                # offsets, and those move when an essay is re-tokenised. So the id is derived from
                # the whole triple, which makes a re-load of the SAME segmentation idempotent and
                # a genuinely changed segmentation a different row.
                span["span_id"] = paper_id_for(
                    spec.source_id,
                    f"{ext}:{span['discourse_type']}:{span['start_char']}:{span['end_char']}")
                span_rows.append(span)
                spans.loaded += 1
        spans.report("spans")

    if a.dry_run:
        print("  DRY RUN — nothing written")
        return {"papers": counts.loaded, "spans": spans.loaded, "partition": split,
                "written": False}

    written = write(spec, papers, span_rows, raw_by_id, batch=a.batch)
    return {"papers": counts.loaded, "spans": spans.loaded, "partition": split,
            "written": True, **written}


# ------------------------------------------------------------------ the write path

_SOURCE = text("""
    INSERT INTO corpus_source
        (source_id, name, snapshot, url, paper_count,
         overlaps_source_id, overlap_note)
    VALUES (:source_id, :name, CAST(:snapshot AS date), :url, :paper_count,
            :overlaps_source_id, :overlap_note)
    ON CONFLICT (source_id) DO UPDATE SET
        name = EXCLUDED.name, snapshot = EXCLUDED.snapshot,
        url = EXCLUDED.url, paper_count = EXCLUDED.paper_count,
        overlaps_source_id = EXCLUDED.overlaps_source_id, overlap_note = EXCLUDED.overlap_note
""")

# ON CONFLICT on the NATURAL key, not the surrogate one. `paper_id` is derived from the same two
# columns, so either would work today — but a corpus re-issued with new ids and the same essays
# would silently double under a surrogate-key conflict, and the unique constraint that actually
# expresses "one essay per source" is the natural one.
_PAPER = text("""
    INSERT INTO corpus_paper
        (paper_id, source_id, external_id, text, text_hash, prompt_name, task_type,
         grade_level, word_count, partition, gender, ell_status, race_ethnicity,
         economically_disadvantaged, disability_status, assignment, source_text)
    VALUES (:paper_id, :source_id, :external_id, :text, :text_hash, :prompt_name, :task_type,
            :grade_level, :word_count, :partition, :gender, :ell_status, :race_ethnicity,
            :economically_disadvantaged, :disability_status, :assignment, :source_text)
    ON CONFLICT (source_id, external_id) DO UPDATE SET
        text = EXCLUDED.text, text_hash = EXCLUDED.text_hash,
        prompt_name = EXCLUDED.prompt_name, task_type = EXCLUDED.task_type,
        grade_level = EXCLUDED.grade_level, word_count = EXCLUDED.word_count,
        partition = EXCLUDED.partition, gender = EXCLUDED.gender,
        ell_status = EXCLUDED.ell_status, race_ethnicity = EXCLUDED.race_ethnicity,
        economically_disadvantaged = EXCLUDED.economically_disadvantaged,
        disability_status = EXCLUDED.disability_status,
        assignment = EXCLUDED.assignment, source_text = EXCLUDED.source_text
""")

# Scores and spans are DELETED for the papers in this load and re-inserted, rather than upserted.
# Neither has a natural key that survives a corpus re-issue — a span is identified by its offsets,
# which move when an essay is re-tokenised — so an upsert would accumulate the old segmentation
# beside the new one and every count downstream would drift upward on each load.
_CLEAR_SCORES = text("DELETE FROM corpus_score WHERE paper_id = ANY(:paper_ids)")
_CLEAR_SPANS = text("DELETE FROM corpus_discourse_span WHERE paper_id = ANY(:paper_ids)")

_SCORE = text("""
    INSERT INTO corpus_score
        (corpus_score_id, paper_id, kind, label, value, scale_min, scale_max, rater_id)
    VALUES (:corpus_score_id, :paper_id, :kind, :label, :value, :scale_min, :scale_max, :rater_id)
""")

_SPAN = text("""
    INSERT INTO corpus_discourse_span
        (span_id, paper_id, discourse_type, start_char, end_char, text, effectiveness)
    VALUES (:span_id, :paper_id, :discourse_type, :start_char, :end_char, :text, :effectiveness)
""")


def write(spec: CorpusSpec, papers: dict, span_rows: list, raw: dict,
          *, batch: int = 1000) -> dict:
    """Upsert one corpus. Idempotent: running it twice leaves the same rows.

    Idempotence is not a nicety here. A bulk load of 26,000 papers WILL be re-run — a connection
    drops, a mapper is corrected, a snapshot is re-issued — and a loader that doubles its corpus on
    the second run corrupts every downstream count in a way nothing detects, because the numbers
    stay plausible.
    """
    from ._db import _engine

    eng = _engine()
    ids = [p["paper_id"] for p in papers.values()]
    done = {"papers": 0, "scores": 0, "spans": 0}

    with eng.begin() as conn:
        # `overlaps_source_id` names a corpus that may not be in this database. That is not a
        # dangling reference to be prevented — it is the fact: PERSUADE overlaps ASAP2 whether or
        # not ASAP2 has been loaded here, and the note explaining why they cannot be used as
        # independent sources is exactly what a person needs BEFORE loading the second one.
        # Migration 0031 drops the foreign key that made load order decide whether the fact could
        # be recorded.
        conn.execute(_SOURCE, {
            "source_id": spec.source_id, "name": spec.name, "snapshot": spec.snapshot,
            "url": spec.url, "paper_count": len(papers),
            "overlaps_source_id": spec.overlaps_source_id, "overlap_note": spec.overlap_note})

        values = list(papers.values())
        for i in range(0, len(values), batch):
            conn.execute(_PAPER, values[i:i + batch])
            done["papers"] += len(values[i:i + batch])

        # Clear before re-inserting, and only for the papers this load carries. A blanket delete by
        # source would remove rows belonging to a partial earlier load that this run does not
        # replace, turning a resumed load into a smaller corpus.
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            conn.execute(_CLEAR_SCORES, {"paper_ids": chunk})
            conn.execute(_CLEAR_SPANS, {"paper_ids": chunk})

        scores = []
        if spec.map_scores:
            for p in values:
                for sc in spec.map_scores(raw[p["external_id"]], p["paper_id"]):
                    sc["corpus_score_id"] = paper_id_for(
                        spec.source_id, f"{p['external_id']}:{sc['kind']}:{sc.get('label') or ''}")
                    scores.append(sc)
        for i in range(0, len(scores), batch):
            conn.execute(_SCORE, scores[i:i + batch])
            done["scores"] += len(scores[i:i + batch])

        for i in range(0, len(span_rows), batch):
            conn.execute(_SPAN, span_rows[i:i + batch])
            done["spans"] += len(span_rows[i:i + batch])

    print(f"  written: {done['papers']:,} papers · {done['scores']:,} scores · "
          f"{done['spans']:,} spans")
    return done
