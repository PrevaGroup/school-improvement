"""Where a verified span sits, so a criterion's justification can be shown in the paper.

The verifier has always returned the offset — its docstring says why, "so a caller can highlight
without searching again" — and the composer threw it away. The console listed quotations beside
the paper instead, which is the same information in the place where it is hardest to use: a
teacher checking whether a 2 is fair wants to see the sentences in the argument they came from.

The whole of this file is about one hazard. An offset is meaningless without the exact string it
indexes, and there are two strings in play: what the student typed, and what the scorer read
after typography was folded. Highlighting the first with offsets into the second misplaces every
mark on any paper with a curly quote in it — silently, and by a different amount each time.
"""
from __future__ import annotations

from scoring.compose import build_packet
from scoring.verify import NORM_VERSION, normalize, verify_all

# A paper with the typography a Google Doc actually produces: curly quotes, an em dash, a
# non-breaking space, and a line break in the middle of a sentence.
PAPER = (
    "Students should have a voice in school rules.\n\n"
    "The court said that students do not “shed their constitutional rights” at the "
    "schoolhouse gate — and that principle still holds.\n"
    "Some people disagree. They say order matters more."
)

SPANS = ["shed their constitutional rights", "Some people disagree."]


def event(**kw) -> dict:
    kept, dropped = verify_all(SPANS, PAPER)
    row = {"node_id": "node-c3", "status": "scored", "level": 2, "confidence": "medium",
           "reason": "The counterclaim is named but not answered.", "reason_code": None,
           "evidence": {"proposed": len(SPANS), "kept": kept, "dropped": dropped,
                        "norm_version": NORM_VERSION},
           "rubric_version": "rv.1", "scoring_configuration_id": "cfg-1",
           "trait_set_version": "ts.1", "form_variant": "fv.1", "event_id": "ev-1",
           "artifact_id": "art-1", "created_at": None, "scorer_type": "ai", "scorer_id": "cfg-1"}
    row.update(kw)
    return row


LABELS = {"node-c3": {"criterion_label": "Counterclaim", "standard_code": "W.9-10.1b",
                      "scale_categories": [1, 2, 3, 4]}}


ARTIFACT = {"artifact_id": "art-1", "student_id": "stu-1", "section_id": "sec-1",
            "task_id": "task-1", "iteration": "final", "window_label": "fall 2026"}


def packet(events=None):
    return build_packet(ARTIFACT, events or [event()], LABELS, [])


# ------------------------------------------------------------------ the offsets survive

def test_a_criterion_carries_where_its_evidence_sits():
    c = packet()["criteria"][0]
    assert len(c["spans"]) == 2
    for s in c["spans"]:
        assert s["at"] >= 0 and s["len"] > 0


def test_the_offsets_land_on_the_words_they_claim():
    """The point of the whole feature. Slice the normalised text at each offset and it must be
    the quotation — not near it, not one character off."""
    body = normalize(PAPER)
    for s in packet()["criteria"][0]["spans"]:
        assert body[s["at"]:s["at"] + s["len"]] == normalize(s["span"])


def test_the_offsets_do_not_land_on_the_words_in_the_raw_text():
    """Not a bug — the reason `text_normalized` exists. This paper has a curly quote and a
    non-breaking space before the second span, so raw and normalised offsets diverge. A console
    that highlighted the raw text with these numbers would be wrong and would look fine."""
    at = packet()["criteria"][0]["spans"][1]["at"]
    quote = normalize(SPANS[1])
    assert PAPER[at:at + len(quote)] != quote
    assert normalize(PAPER)[at:at + len(quote)] == quote


def test_a_span_the_verifier_dropped_has_no_position():
    """A fabricated quotation is not somewhere in the paper. It has no offset, and giving it one
    would put a highlight over words the model invented."""
    kept, dropped = verify_all(["The court said no such thing."], PAPER)
    e = event(evidence={"proposed": 1, "kept": kept, "dropped": dropped,
                        "norm_version": NORM_VERSION})
    c = packet([e])["criteria"][0]
    assert c["spans"] == []
    assert c["evidence_dropped"] == 1


def test_positions_and_quotations_describe_the_same_spans():
    """Two lists that can disagree will. `evidence` is what the teacher reads; `spans` is where
    it is shown. A criterion whose lists differed would highlight one thing and quote another."""
    c = packet()["criteria"][0]
    assert [s["span"] for s in c["spans"]] == c["evidence"]


def test_an_old_evidence_row_without_offsets_is_dropped_rather_than_guessed():
    """Scored before positions were kept. A missing offset is not a zero — `at: 0` would put the
    highlight on the first words of the paper, which is a confident wrong answer."""
    e = event(evidence={"proposed": 1, "norm_version": "old",
                        "kept": [{"span": "Students should have a voice"}], "dropped": []})
    c = packet([e])["criteria"][0]
    assert c["spans"] == []
    assert c["evidence"] == ["Students should have a voice"]
