"""PERSUADE 2.0's three instruments, as the raters were given them.

Transcribed from the rating forms — `persuade_2.0_holistic_rating_form_independent.pdf`,
`persuade_2.0_holistic_rating_form_text_dependent.pdf`, and the argumentation-elements rubric —
not reconstructed from a description of them. That distinction is the whole reason this module
exists as data rather than as prose in a seed script.

## Why the exact text matters

Anchor calibration asks how severe OUR rater is against a known standard. If the model is shown
descriptors we wrote and the humans used descriptors PERSUADE wrote, the estimated severity
confounds "our rater is harsher" with "our rubric says something different" — and there is no way
to separate them afterwards. The number would look exactly as legitimate either way.

## Two holistic rubrics, not one

Independent and text-dependent are separate rating forms, and the corpus splits almost evenly
between them (50.5% / 49.5%). The text-dependent form asks for evidence "taken from the source
text(s)"; the independent form does not. Those are different constructs, the raters were given
different instruments, and a system that could hold only one rubric would have had to pretend
otherwise. They get separate identifiers.

The two holistic traits stay separate: the whole scale is described differently on each form.

## Six shared element traits, and two evidence traits

The argumentation elements are where the many-to-many earns its keep. Lead, Position, Claim,
Counterclaim, Rebuttal and Concluding summary mean the same thing whether or not a source text was
supplied — a counterclaim is a counterclaim. Those six carry ONE identifier each and appear in both
element rubrics, which is how this registry declares that two rubrics measure one thing, and the
only mechanism that could place both halves of PERSUADE on one metric.

Evidence is the exception, and it is the same exception the holistic forms make: in a text-
dependent task the evidence must come from the source. That is a different construct, so it is a
different trait.

Ten traits, four rubrics. Decided by the product manager, 2026-09-08.

## Conventions IS on this scale, and that has a consequence

Every holistic descriptor names grammar, usage and mechanics: "free of most errors" at 6,
"pervasive errors ... that persistently interfere with meaning" at 1. The LDC trait set this
system was built around deliberately excludes conventions — the scoring prompt says so, and stop
condition 2 exists to detect a scorer that has let it in.

So a matched-pairs test must NOT be run against these nodes. Adding conventions errors to a paper
SHOULD move a PERSUADE holistic score, and a stop condition firing here would be reporting the
rubric rather than a defect. `CONVENTIONS_IN_CONSTRUCT` marks that, so the exclusion is a property
of the node rather than something a person has to remember.

## The effectiveness rubric is here and cannot be used yet

Seven elements at three levels — the multi-trait instrument that severity uniformity across
criteria would need. The downloaded release ships the SEGMENTATION without the ratings:
`corpus_discourse_span.effectiveness` is NULL for all 236,906 rows. So this is registered as the
instrument it is, and there is nothing human to compare a model score against until a release
with effectiveness ratings arrives.
"""
from __future__ import annotations

import uuid

# Same namespace shape as `registry/seed_demo.py`: derived ids, so re-seeding is idempotent and a
# rubric that has been scored against keeps its identity across reloads.
NS = uuid.UUID("6f2a1c94-0d3b-4f8e-9a71-5c2d8e4b17aa")

PUBLISHER = "PERSUADE 2.0 (Crossley et al.)"
# The corpus repository, which is where the terms are STATED. Deliberately not a licence name.
#
# There was a `LICENCE_NOTE = "CC BY 4.0"` here and it was wrong. Nobody in this repo is the
# licensor of PERSUADE, the terms can differ between the corpus and the rating forms and can
# change between snapshots, and a permissive licence invented on our side is the error that
# matters — it authorises redistribution the publisher may not grant. A URL sends a reader to the
# party who can actually answer; a string tells them what we remembered.
TERMS_URL = "https://github.com/scrosseye/persuade_corpus_2.0"
GRADE_BAND = "6-12"          # the corpus spans grades 6 through 12

# Provenance per trait. `transcribed` is the rating form's own words; `adapted` is authored text
# following the form's own pattern, and it says who decided. A descriptor nobody can trace is a
# descriptor that will later be cited as PERSUADE's.
TRANSCRIBED = "transcribed from the PERSUADE 2.0 rating form"
ADAPTED = ("adapted from the PERSUADE 2.0 element rubric by adding the source-text requirement "
           "the holistic text-dependent form uses; decided by the product manager 2026-09-08")


def rubric_id(key: str) -> str:
    return str(uuid.uuid5(NS, f"rubric:{key}"))


def node_id(key: str) -> str:
    return str(uuid.uuid5(NS, f"trait:{key}"))


# ------------------------------------------------------------------ holistic, 1-6

_HOLISTIC_COMMON = {
    "6": ("An essay in this category demonstrates clear and consistent mastery, although it may "
          "have a few minor errors. A typical essay effectively and insightfully develops a point "
          "of view on the issue and demonstrates outstanding critical thinking, using clearly "
          "appropriate examples, reasons, and other evidence{source} to support its position; the "
          "essay is well organized and clearly focused, demonstrating clear coherence and smooth "
          "progression of ideas; the essay exhibits skillful use of language, using a varied, "
          "accurate, and apt vocabulary and demonstrates meaningful variety in sentence "
          "structure; the essay is free of most errors in grammar, usage, and mechanics."),
    "5": ("An essay in this category demonstrates reasonably consistent mastery, although it will "
          "have occasional errors or lapses in quality. A typical essay effectively develops a "
          "point of view on the issue and demonstrates strong critical thinking, generally using "
          "appropriate examples, reasons, and other evidence{source} to support its position; the "
          "essay is well organized and focused, demonstrating coherence and progression of ideas; "
          "the essay exhibits facility in the use of language, using appropriate vocabulary "
          "demonstrates variety in sentence structure; the essay is generally free of most errors "
          "in grammar, usage, and mechanics."),
    "4": ("An essay in this category demonstrates adequate mastery, although it will have lapses "
          "in quality. A typical essay develops a point of view on the issue and demonstrates "
          "competent critical thinking, using adequate examples, reasons, and other "
          "evidence{source} to support its position; the essay is generally organized and "
          "focused, demonstrating some coherence and progression of ideas exhibits adequate; the "
          "essay may demonstrate inconsistent facility in the use of language, using generally "
          "appropriate vocabulary demonstrates some variety in sentence structure; the essay may "
          "have some errors in grammar, usage, and mechanics."),
    "3": ("An essay in this category demonstrates developing mastery, and is marked by ONE OR "
          "MORE of the following weaknesses: develops a point of view on the issue, demonstrating "
          "some critical thinking, but may do so inconsistently or use inadequate examples, "
          "reasons, or other evidence{source} to support its position; the essay is limited in "
          "its organization or focus, or may demonstrate some lapses in coherence or progression "
          "of ideas displays; the essay may demonstrate facility in the use of language, but "
          "sometimes uses weak vocabulary or inappropriate word choice and/or lacks variety or "
          "demonstrates problems in sentence structure; the essay may contain an accumulation of "
          "errors in grammar, usage, and mechanics."),
    "2": ("An essay in this category demonstrates little mastery, and is flawed by ONE OR MORE of "
          "the following weaknesses: develops a point of view on the issue that is vague or "
          "seriously limited, and demonstrates weak critical thinking, providing inappropriate or "
          "insufficient examples, reasons, or other evidence{source} to support its position; the "
          "essay is poorly organized and/or focused, or demonstrates serious problems with "
          "coherence or progression of ideas; the essay displays very little facility in the use "
          "of language, using very limited vocabulary or incorrect word choice and/or "
          "demonstrates frequent problems in sentence structure; the essay contains errors in "
          "grammar, usage, and mechanics so serious that meaning is somewhat obscured."),
    "1": ("An essay in this category demonstrates very little or no mastery, and is severely "
          "flawed by ONE OR MORE of the following weaknesses: develops no viable point of view "
          "on the issue, or provides little or no evidence to support its position; the essay is "
          "disorganized or unfocused, resulting in a disjointed or incoherent essay; the essay "
          "displays fundamental errors in vocabulary and/or demonstrates severe flaws in sentence "
          "structure; the essay contains pervasive errors in grammar, usage, or mechanics that "
          "persistently interfere with meaning."),
}

# The ONLY difference between the two forms, and it is a difference of construct: the
# text-dependent form requires the evidence to come from the source text.
_SOURCE_CLAUSE = " taken from the source text(s)"

HOLISTIC_SCALE = [1, 2, 3, 4, 5, 6]

# The instruction at the top of both forms. Carried because it states the interval assumption the
# rating scale model relies on — "the distance between each grade should be considered equal" —
# which is an assertion the raters were given and which MFRM then tests rather than assumes.
HOLISTIC_INSTRUCTION = (
    "After reading each essay, assign a holistic score using a scale between 1 (minimum) and 6 "
    "(maximum). The distance between each grade (e.g. 1-2, 3-4, 4-5) should be considered equal.")


def holistic(task: str) -> dict:
    """One holistic rubric. `task` is 'independent' or 'text_dependent'."""
    if task not in ("independent", "text_dependent"):
        raise ValueError(f"unknown PERSUADE task form {task!r}")
    source = _SOURCE_CLAUSE if task == "text_dependent" else ""
    key = f"persuade20-holistic-{task}"
    nid = node_id(key)
    label = ("Overall argumentative writing quality (source-based)"
             if task == "text_dependent" else "Overall argumentative writing quality")
    return {
        "rubric_id": rubric_id(key),
        "name": ("PERSUADE 2.0 Holistic — Text Dependent" if task == "text_dependent"
                 else "PERSUADE 2.0 Holistic — Independent"),
        "publisher": PUBLISHER,
        "external_ref": key,
        "grade_band": GRADE_BAND,
        "traits": [{
            "node_id": nid,
            "external_ref": key,
            "criterion_label": label,
            # NOT a CCSS code. PERSUADE's holistic scale is its own instrument, and inventing a
            # standard alignment here would assert a mapping nobody made.
            "standard_code": "PERSUADE.HOLISTIC",
            "grade_band": GRADE_BAND,
            "scale_categories": HOLISTIC_SCALE,
            "kind": "anchor",
            "source": "PERSUADE 2.0 holistic rating form",
            "descriptors": {k: v.format(source=source) for k, v in _HOLISTIC_COMMON.items()},
            "instruction": HOLISTIC_INSTRUCTION,
            # Every descriptor names grammar, usage and mechanics. Recorded on the node so the
            # exclusion from stop condition 2 is a property of the data rather than a thing
            # somebody has to remember.
            "conventions_in_construct": True,
            "provenance": TRANSCRIBED,
        }],
    }


# ------------------------------------------------------------------ element effectiveness, 1-3

# "Effective" / "Adequate" / "Ineffective" as ordered categories. The rubric gives three levels
# with no numeric labels; 3/2/1 preserves the order and the direction (higher is better), which is
# what the rating scale model needs. The mapping is recorded rather than assumed because a reader
# meeting a "2" later has no way to recover which word it was.
EFFECTIVENESS_SCALE = [1, 2, 3]
EFFECTIVENESS_WORDS = {3: "Effective", 2: "Adequate", 1: "Ineffective"}

# The six elements whose construct does not change with the task. A counterclaim is a counterclaim
# whether or not a source text was supplied, so each carries ONE identifier and appears in both
# element rubrics. That shared identifier is the anchor that can place the two halves of PERSUADE
# on one metric; own them to a rubric each and the halves float apart forever.
_SHARED_ELEMENTS = {
    "lead": ("Lead", {
        "3": "The lead grabs the reader's attention and strongly points toward the position.",
        "2": "The lead attempts to grab the reader's attention and points toward the position.",
        "1": "The lead may not grab the readers' attention and may not point to the position."}),
    "position": ("Position", {
        "3": "The position states a clear stance closely related to the topic.",
        "2": "The position addresses the topic but generally repeats the prompt's stance.",
        "1": "The position is not relevant to the topic, and/or it shows no clear stance."}),
    "claim": ("Claim", {
        "3": ("The claim is closely relevant to the position and backs up the position with "
              "specific points or perspectives. The claim is valid and acceptable."),
        "2": ("The claim relates to the position but may simply repeat part of the position or "
              "state a claim without support. The claim is moderately valid and acceptable."),
        "1": ("The claim is irrelevant to the position. It may also be weak and/or not "
              "acceptable.")}),
    "counterclaim": ("Counterclaim", {
        "3": ("The counterclaim is reasonable and relevant. It represents a valid objection to "
              "the position."),
        "2": ("The counterclaim is not quite a reasonable opposing opinion, or it is not closely "
              "relevant to the position."),
        "1": "The counterclaim is neither reasonable nor relevant."}),
    "rebuttal": ("Rebuttal", {
        "3": "The rebuttal directly answers and refutes the counterclaim.",
        "2": ("The rebuttal does not answer the counterclaim directly and it is not strong "
              "and/or valid."),
        "1": "The rebuttal misses the target. It does not refute the counterclaim."}),
    "concluding_summary": ("Concluding summary", {
        "3": ("The concluding summary effectively restates the claims using different wording. It "
              "may readdress the claims in light of the evidence provided."),
        "2": ("The concluding summary merely copies the claims or may restates only part of the "
              "claims. It may partially misrepresent the claims."),
        "1": ("The concluding summary is irrelevant to the claims. The conclusion may also "
              "misrepresent the claims.")}),
}

# Evidence is the exception, and it is the same exception the holistic forms make: a text-dependent
# task requires the evidence to come from the source. Two constructs, two traits.
#
# The rating form has ONE evidence descriptor set, written without a source requirement, so the
# independent trait is transcribed and the sourced one is ADAPTED — the source clause added
# following the pattern the holistic text-dependent form uses. Marked as adapted rather than
# passed off as PERSUADE's, because a descriptor nobody can trace is one that will later be cited
# as theirs.
_EVIDENCE = {
    "3": ("The evidence is closely relevant to the claim they support and back up the claim "
          "objectively with concrete facts, examples, research, statistics, or studies{source}. "
          "The reasons in the evidence support the claim and are sound and well substantiated."),
    "2": ("The evidence is not closely relevant to the claim it supports. The evidence contains "
          "some detailed examples{source} but they may not be relevant to each other and only "
          "loosely bound together. The evidence uses some unsubstantiated or unsound claims or "
          "assumptions."),
    "1": ("The evidence is irrelevant to the claim it backs up and provide few valid "
          "examples{source}. The evidence uses unsubstantiated assumptions that sound quite "
          "unacceptable."),
}

_EVIDENCE_SOURCE_CLAUSE = " taken from the source text(s)"


def _trait(key: str, label: str, descriptors: dict, *, ordinal: int,
           provenance: str) -> dict:
    return {
        "node_id": node_id(key),
        "external_ref": key,
        "criterion_label": label,
        "standard_code": "PERSUADE.ELEMENT",
        "grade_band": GRADE_BAND,
        "scale_categories": EFFECTIVENESS_SCALE,
        "kind": "anchor",
        "source": "PERSUADE argumentation elements rubric (Table 2)",
        "descriptors": descriptors,
        "instruction": ("Rate this argumentation element as Effective (3), Adequate (2) or "
                        "Ineffective (1) using the descriptors below."),
        # Every element descriptor is about argumentative function, so matched-pairs testing is
        # legitimate here and not against the holistic nodes.
        "conventions_in_construct": False,
        "provenance": provenance,
        "ordinal": ordinal,
    }


def shared_element_traits() -> list[dict]:
    """The six traits both element rubrics share. One identifier each."""
    return [_trait(f"persuade20-element:{slug}", name, desc, ordinal=i, provenance=TRANSCRIBED)
            for i, (slug, (name, desc)) in enumerate(_SHARED_ELEMENTS.items(), start=1)]


def evidence_trait(task: str) -> dict:
    """The evidence trait for one task form. Two constructs, two identifiers."""
    if task not in ("independent", "text_dependent"):
        raise ValueError(f"unknown PERSUADE task form {task!r}")
    sourced = task == "text_dependent"
    clause = _EVIDENCE_SOURCE_CLAUSE if sourced else ""
    return _trait(
        f"persuade20-element:evidence-{task}",
        "Evidence (source-based)" if sourced else "Evidence",
        {k: v.format(source=clause) for k, v in _EVIDENCE.items()},
        ordinal=7, provenance=ADAPTED if sourced else TRANSCRIBED)


def elements(task: str) -> dict:
    """One element rubric: the six shared traits plus this task's evidence trait."""
    key = f"persuade20-argumentation-elements-{task}"
    return {
        "rubric_id": rubric_id(key),
        "name": ("PERSUADE 2.0 Argumentation Elements — Text Dependent" if task == "text_dependent"
                 else "PERSUADE 2.0 Argumentation Elements — Independent"),
        "publisher": PUBLISHER,
        "external_ref": key,
        "grade_band": GRADE_BAND,
        "traits": shared_element_traits() + [evidence_trait(task)],
    }


def all_rubrics() -> list[dict]:
    """Four rubrics over ten distinct traits: two holistic, six shared elements, two evidence."""
    return [holistic("independent"), holistic("text_dependent"),
            elements("independent"), elements("text_dependent")]


def distinct_traits() -> dict[str, dict]:
    """node_id -> trait, deduplicated. The shared six appear in two rubrics and are ONE trait."""
    out: dict[str, dict] = {}
    for r in all_rubrics():
        for t in r["traits"]:
            out.setdefault(t["node_id"], t)
    return out


# Nodes whose construct INCLUDES conventions. Stop condition 2 must skip these: adding grammar
# errors is supposed to move a score here, and a trigger would be reporting the instrument rather
# than a defect. Computed at import from the traits themselves, so a new node cannot be added
# without landing on the right side of it.
CONVENTIONS_IN_CONSTRUCT: frozenset[str] = frozenset(
    nid for nid, t in distinct_traits().items() if t["conventions_in_construct"])
