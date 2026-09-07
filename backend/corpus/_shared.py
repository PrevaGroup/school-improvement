"""The shared runner every corpus loader calls. One spec plus this; the loaders stay thin.

Follows `public_metrics/_shared.py`: read from a local path or a gs:// URI, conform, upsert, and
print what was loaded, skipped and excluded. A loader that cannot say what it dropped is a loader
nobody can debug.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping

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
    licence: str | None = None
    url: str | None = None
    snapshot: str | None = None
    spans_file: str | None = None
    overlaps_source_id: str | None = None
    overlap_note: str | None = None
    # row -> a paper dict, or None to skip (with a reason recorded by the mapper)
    map_paper: Callable[[Mapping[str, str]], dict[str, Any] | None] = None
    map_scores: Callable[[Mapping[str, str], str], list[dict[str, Any]]] = None
    map_span: Callable[[Mapping[str, str]], dict[str, Any] | None] = None


def rows(path: str) -> Iterator[dict[str, str]]:
    with open(path, encoding="utf8", errors="replace", newline="") as fh:
        yield from csv.DictReader(fh)


def blank_to_none(v: str | None) -> str | None:
    """A blank demographic is NOT a label. Preserving it as NULL is what stops 'unknown' quietly
    becoming a subgroup in a fairness table."""
    v = (v or "").strip()
    return v or None


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=os.environ.get("CORPUS_DIR", "."))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
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
    for i, row in enumerate(rows(papers_path)):
        if a.limit and i >= a.limit:
            break
        counts.read += 1
        paper = spec.map_paper(row)
        if paper is None:
            counts.skip("mapper rejected the row")
            continue
        h = text_hash(paper["text"])
        if h in hashes:
            counts.skip("duplicate essay text within this source")
            continue
        hashes[h] = paper["external_id"]
        paper["text_hash"] = h
        paper["source_id"] = spec.source_id
        paper["partition"] = partition_for(spec.source_id, paper["external_id"])
        papers[paper["external_id"]] = paper
        counts.loaded += 1
    counts.report("papers")

    split = {"calibration": 0, "validation": 0}
    for p in papers.values():
        split[p["partition"]] += 1
    print(f"      partition: {split['calibration']:,} calibration / "
          f"{split['validation']:,} validation")

    spans = Counts()
    if spec.spans_file:
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
                spans.loaded += 1
        spans.report("spans")

    if a.dry_run:
        print("  DRY RUN — nothing written")
    return {"papers": counts.loaded, "spans": spans.loaded, "partition": split}
