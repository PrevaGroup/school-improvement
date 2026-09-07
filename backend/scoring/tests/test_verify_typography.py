"""Does real-world typography defeat exact-substring matching?

THE CIRCULARITY THIS EXISTS TO BREAK. `verify.normalize()` folds a fixed list of characters, and
until now every test of it ran against prose written with exactly the characters on that list. A
0/57 drop rate on that corpus says the verifier agrees with itself. What it does not say is whether
a span survives the trip out of Google Docs or Word, which is where every real paper comes from.

That question does not need a corpus. It needs a paragraph containing every typographic hazard those
editors actually produce, which is what this file is. Reaching for 840MB of PERSUADE to answer it
was the wrong instinct — the corpus answers a different question (severity, subgroup fairness,
a replay baseline), and this one is a unit test.

WHAT A FAILURE HERE WOULD MEAN. Not that the verifier is broken — that its normalization is too
narrow, and that criteria would abstain on real papers for reasons that have nothing to do with
the writing. The drop would look like "the model fabricated evidence" and would actually be "the
student's apostrophe was curly". That is a silent, systematic, invisible failure and precisely the
kind this subsystem is built to refuse.
"""
from __future__ import annotations

import pytest

from scoring.verify import normalize, verify

# What a Google Docs or Word export actually contains. Each entry is (name, as-exported, as-typed):
# a model reading the exported text and echoing it back in its own straight-quoted style must still
# verify, and a model echoing the export verbatim must verify too.
HAZARDS = [
    ("curly apostrophe", "the Court’s reasoning", "the Court's reasoning"),
    ("curly double quotes", "“schoolhouse gate”", '"schoolhouse gate"'),
    ("single curly quotes", "‘substantial’ disruption", "'substantial' disruption"),
    ("em dash", "narrowed it — twice", "narrowed it - twice"),
    ("en dash", "1969–1988 cases", "1969-1988 cases"),
    ("minus sign", "a − result", "a - result"),
    ("ellipsis character", "and then… nothing", "and then... nothing"),
    ("non-breaking space", "Tinker v. Des Moines", "Tinker v. Des Moines"),
    ("narrow no-break space", "50 000 students", "50 000 students"),
    ("thin space", "p. 14 of the opinion", "p. 14 of the opinion"),
]


@pytest.mark.parametrize("name,exported,typed", HAZARDS, ids=[h[0] for h in HAZARDS])
def test_a_span_survives_the_editor_it_came_out_of(name, exported, typed):
    """The paper carries the exported form; the model may echo either. Both must verify."""
    paper = f"Before the span. {exported} And after it."
    assert verify(exported, paper)["ok"], f"{name}: verbatim echo failed"
    assert verify(typed, paper)["ok"], f"{name}: straight-quoted echo failed"


@pytest.mark.parametrize("name,exported,typed", HAZARDS, ids=[h[0] for h in HAZARDS])
def test_it_works_the_other_way_round_too(name, exported, typed):
    """A paper typed with straight quotes and a model that prettifies its echo. Same folding, and
    a normalization that only worked in one direction would be worse than none — it would look
    fine on whichever corpus was tested first."""
    paper = f"Before the span. {typed} And after it."
    assert verify(exported, paper)["ok"], f"{name}: prettified echo failed"


def test_a_whole_paragraph_of_hazards_at_once():
    """Real papers do not contain one hazard. They contain all of them, in one sentence."""
    exported = ("The Court’s “marked distinction” — drawn in Bethel v. "
                "Fraser, 1969–1988 — narrowed Tinker… quietly.")
    typed = ('The Court\'s "marked distinction" - drawn in Bethel v. Fraser, 1969-1988 - '
             "narrowed Tinker... quietly.")
    paper = f"An opening sentence. {exported} A closing one."
    assert verify(exported, paper)["ok"]
    assert verify(typed, paper)["ok"]


def test_line_wrapping_and_stray_whitespace_do_not_break_a_span():
    """A .docx paragraph pulled apart across runs arrives with newlines and doubled spaces where
    the student typed one. The words are the same and the span is the same."""
    paper = "The reasoning is about\n   vulgarity,  but the effect\tis about power."
    assert verify("The reasoning is about vulgarity, but the effect is about power.", paper)["ok"]


# ------------------------------------------------------------------ what must still fail


def test_case_is_not_folded():
    """A scorer shown 'the court' where the student wrote 'the Court' is being shown something the
    student did not write, and quotation accuracy is part of what is being scored."""
    assert not verify("the court erred", "She argued the Court erred badly.")["ok"]


def test_a_dropped_word_still_fails():
    """The folding must not become so generous that it stops catching a paraphrase."""
    assert not verify("the reasoning is about power", "The reasoning is about vulgarity.")["ok"]


def test_a_fabricated_sentence_still_fails():
    assert not verify("The Court overruled Tinker entirely.",
                      "Tinker is still the standard, and it is a demanding one.")["ok"]


def test_normalization_does_not_change_which_words_are_present():
    """Every substitution maps a character onto one that means the same thing. If one of them ever
    removed or merged a word, the verifier would start passing spans the student did not write."""
    for _, exported, typed in HAZARDS:
        assert normalize(exported).split() == normalize(typed).split(), exported
