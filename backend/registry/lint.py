"""The registry linter — the fourth enforcement mechanism.

SIP holds together on three: the import boundary test, the route contract test, and the eval loop.
None of them can see this class of defect — an error authored into configuration, invisible at run
time, applying to every artifact in a section. The construct audit found five such defects by hand
in a single module; each one below is that finding turned into a rule.

TWO CLASSES, AND THE DIFFERENCE MATTERS.

  BLOCKING   the registry is internally incoherent — an identifier meaning two things, a node with
             no scale, a linking sequence missing its anchors. Publication is refused.
  ADVISORY   a judgment the linter cannot make: a construct taught and scored nowhere, a cell
             stacking conditions. These clear only with a recorded acknowledgment naming a reason,
             and the acknowledgment becomes part of the version record — so the next reader sees a
             judgment that was made rather than a check that was skipped.

WHAT THIS DELIBERATELY DOES NOT FLAG. Scale structures differing across nodes. Six structures
across seven instruments is not an inconsistency, because there was never one thing they were being
inconsistent about: where criteria differ, the constructs differ, and the scale belongs to the node.
Flagging it would be flagging the data for being what it is.

Pure functions over dicts. No database handle — the SQL that loads a registry belongs to the caller,
and keeping the rules separable is what lets them be tested exhaustively without a Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

BLOCKING, ADVISORY = "blocking", "advisory"

# Severity differs by family, and the asymmetry is itself a finding rather than a convenience.
# On the READING side the strands diverge materially — at Anchor 6, RI is single-text and rhetorical
# while RH is cross-author and evidentiary — so a substitution is a construct error that produces a
# ceiling on the item. On the WRITING side W and WHST are near-verbatim in CCSS, so the same swap is
# harmless. That asymmetry is the evidence that a generic RI/RL mini-task rubric library exists and
# an RH one does not, which is worth surfacing rather than flattening.
STRAND_SIBLINGS: dict[str, tuple[tuple[str, ...], str]] = {
    "RI": (("RH", "RL"), BLOCKING),
    "RH": (("RI", "RL"), BLOCKING),
    "RL": (("RI", "RH"), BLOCKING),
    "W": (("WHST",), ADVISORY),
    "WHST": (("W",), ADVISORY),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    subject: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"[{self.severity}] {self.rule} on {self.subject}: {self.message}"


@dataclass
class Registry:
    """The slice of registry content a lint pass reads. Plain dicts, loaded by the caller."""
    # standard -> skill -> rubric -> trait -> criteria. Skills and rubrics arrived in 0019; the
    # defaults keep every caller that predates them working, and a registry with no rubrics simply
    # produces no rubric findings rather than crashing.
    skills: Sequence[Mapping[str, Any]] = field(default_factory=list)
    rubrics: Sequence[Mapping[str, Any]] = field(default_factory=list)
    rubric_traits: Sequence[Mapping[str, Any]] = field(default_factory=list)
    nodes: Sequence[Mapping[str, Any]] = field(default_factory=list)
    versions: Sequence[Mapping[str, Any]] = field(default_factory=list)
    tasks: Sequence[Mapping[str, Any]] = field(default_factory=list)
    sites: Sequence[Mapping[str, Any]] = field(default_factory=list)
    site_nodes: Sequence[Mapping[str, Any]] = field(default_factory=list)
    # module_key -> True when its tasks are declared part of a linking sequence
    linking_modules: Sequence[str] = field(default_factory=list)
    # constructs the module teaches, by module_key — supplied by the author, not inferable
    taught_constructs: Mapping[str, Sequence[str]] = field(default_factory=dict)
    acknowledgments: Mapping[str, str] = field(default_factory=dict)   # "rule:subject" -> reason


# --------------------------------------------------------------------------- #
# Blocking rules
# --------------------------------------------------------------------------- #
def check_identifier_integrity(r: Registry) -> list[Finding]:
    """One identifier, one meaning.

    The identifier is the identity; the composite is the integrity constraint. An identifier
    appearing with two scale structures, two standards or two grade bands is a hard error rather
    than something to reconcile — a difference in category count is exactly the evidence that two
    constructs were drawn, so the same identifier cannot sit on both.
    """
    seen: dict[str, dict[str, Any]] = {}
    out: list[Finding] = []
    for n in r.nodes:
        nid = n["node_id"]
        shape = {"standard_code": n.get("standard_code"),
                 "grade_band": n.get("grade_band"),
                 "scale_categories": tuple(n.get("scale_categories") or ())}
        if nid in seen and seen[nid] != shape:
            differing = [k for k in shape if seen[nid][k] != shape[k]]
            out.append(Finding(
                "identifier_integrity", BLOCKING, nid,
                f"the same identifier appears with different {', '.join(differing)}. The "
                f"identifier is the identity — two things differing on standard, scale or grade "
                f"band are two nodes and need two identifiers."))
        seen[nid] = shape
    return out


def check_scale_declared(r: Registry) -> list[Finding]:
    """You cannot fit what you cannot read. An undeclared or single-category scale is unscoreable,
    and it is the one scale-related thing the linter does have an opinion about."""
    out = []
    for n in r.nodes:
        cats = n.get("scale_categories")
        if not cats:
            out.append(Finding("scale_declared", BLOCKING, n["node_id"],
                               "no scale categories declared — the node cannot be fitted."))
        elif len(cats) < 2:
            out.append(Finding("scale_declared", BLOCKING, n["node_id"],
                               f"a scale needs at least two categories, found {list(cats)}."))
        elif list(cats) != sorted(cats):
            out.append(Finding("scale_declared", BLOCKING, n["node_id"],
                               f"categories are not in order: {list(cats)}."))
    return out


def check_strand_substitution(r: Registry) -> list[Finding]:
    """A node scored on its sibling strand's guide.

    Flagged when a node's own standard and the task's tagged standard are siblings under one anchor
    but not the same code. RI.11-12.6 standing in for RH.11-12.6 is single-text rhetoric replacing
    cross-author evidentiary reasoning — the construct error the crosswalk found three times.
    """
    by_task = {t["task_id"]: t for t in r.tasks}
    site_by_id = {s["site_id"]: s for s in r.sites}
    node_by_id = {n["node_id"]: n for n in r.nodes}
    out = []
    for sn in r.site_nodes:
        site = site_by_id.get(sn["site_id"])
        node = node_by_id.get(sn["node_id"])
        if not site or not node:
            continue
        task = by_task.get(site["task_id"])
        if not task:
            continue
        node_code = (node.get("standard_code") or "")
        node_prefix, _, node_rest = node_code.partition(".")
        for tagged in (task.get("standards") or []):
            t_prefix, _, t_rest = str(tagged).partition(".")
            siblings, severity = STRAND_SIBLINGS.get(t_prefix, ((), BLOCKING))
            if (t_rest and t_rest == node_rest and t_prefix != node_prefix
                    and node_prefix in siblings):
                why = ("these strands diverge materially — one is single-text and rhetorical, the "
                       "other cross-author and evidentiary — so expect a ceiling on the item "
                       "rather than a label mismatch"
                       if severity == BLOCKING else
                       "these are near-verbatim in CCSS, so the swap is probably harmless; "
                       "recorded because the reading-side asymmetry is itself the finding")
                out.append(Finding(
                    "strand_substitution", severity, node["node_id"],
                    f"task {task['task_id']} is tagged {tagged} but this node scores {node_code}. "
                    f"Strand siblings under one anchor: {why}."))
    return out


def check_anchor_coverage(r: Registry) -> list[Finding]:
    """Anchor nodes must appear at every site of a task inside a linking sequence.

    A linking claim rests on the anchors being present throughout. A sequence missing one at any
    site links through fewer items than it claims to, and nothing downstream would notice.
    """
    if not r.linking_modules:
        return []
    anchors = {n["node_id"] for n in r.nodes if n.get("kind") == "anchor"}
    if not anchors:
        return []
    by_task = {t["task_id"]: t for t in r.tasks}
    nodes_at_site: dict[str, set[str]] = {}
    for sn in r.site_nodes:
        nodes_at_site.setdefault(sn["site_id"], set()).add(sn["node_id"])
    out = []
    for site in r.sites:
        task = by_task.get(site["task_id"])
        if not task or task.get("module_key") not in r.linking_modules:
            continue
        if not site.get("is_measurement_occasion"):
            continue   # only occasions carry the linking claim
        missing = sorted(anchors - nodes_at_site.get(site["site_id"], set()))
        if missing:
            out.append(Finding(
                "anchor_coverage", BLOCKING, site["site_id"],
                f"measurement occasion in a linking sequence is missing anchor node(s) {missing}. "
                f"The sequence links through fewer items than it claims to."))
    return out


def check_descriptor_change_acknowledged(r: Registry) -> list[Finding]:
    """A descriptor edit either clarified a construct or replaced it. Only a person can say which.

    The linter cannot answer it; it can refuse to let it go unasked. A new version whose descriptors
    differ from the published one needs an acknowledgment before it publishes — and that
    acknowledgment becomes part of the version record.
    """
    published: dict[str, Mapping[str, Any]] = {}
    for v in r.versions:
        if v.get("status") == "published":
            prev = published.get(v["node_id"])
            if prev is None or v["version"] > prev["version"]:
                published[v["node_id"]] = v
    out = []
    for v in r.versions:
        if v.get("status") != "draft":
            continue
        prev = published.get(v["node_id"])
        if prev is None or prev["version"] >= v["version"]:
            continue
        if prev.get("descriptors") == v.get("descriptors"):
            continue
        if not v.get("construct_unchanged_ack"):
            out.append(Finding(
                "descriptor_change_ack", BLOCKING, v["node_version_id"],
                f"descriptors changed from v{prev['version']} without an acknowledgment. If the "
                f"edit clarified the same construct, record that; if it replaced it, this needs a "
                f"new node identifier rather than a new version."))
    return out


# --------------------------------------------------------------------------- #
# Advisory rules — clear only with a recorded reason
# --------------------------------------------------------------------------- #
def check_taught_but_unscored(r: Registry) -> list[Finding]:
    """A construct the module teaches and scores nowhere.

    Advisory, not blocking: the gap may be deliberate, and the diagnostic channel exists precisely
    to address taught-but-unscored constructs without pretending they are measured. What the linter
    refuses is for the gap to be SILENT — the crosswalk found counterclaim taught in three places
    and scored in none, and nothing in the system would have said so.
    """
    scored_labels: dict[str, set[str]] = {}
    node_by_id = {n["node_id"]: n for n in r.nodes}
    site_by_id = {s["site_id"]: s for s in r.sites}
    task_by_id = {t["task_id"]: t for t in r.tasks}
    for sn in r.site_nodes:
        site = site_by_id.get(sn["site_id"])
        node = node_by_id.get(sn["node_id"])
        if not site or not node:
            continue
        task = task_by_id.get(site["task_id"])
        if not task:
            continue
        if node.get("kind") == "diagnostic_only":
            continue
        scored_labels.setdefault(task["module_key"], set()).add(
            (node.get("criterion_label") or "").strip().lower())
    out = []
    for module_key, taught in r.taught_constructs.items():
        scored = scored_labels.get(module_key, set())
        for construct in taught:
            if construct.strip().lower() not in scored:
                out.append(Finding(
                    "taught_but_unscored", ADVISORY, f"{module_key}:{construct}",
                    f"'{construct}' is taught in {module_key} and scored by no node. A clean "
                    f"profile will not mean that area is fine."))
    return out


def check_stacked_conditionals(r: Registry) -> list[Finding]:
    """A rubric cell holding several conditional judgments.

    Two raters can score the same paper on different clauses, which shows up as severe misfit and
    is nearly impossible to diagnose from the estimates alone. The C3 cell the crosswalk found
    stacks three sub-judgments each prefaced 'when relevant'.
    """
    out = []
    for v in r.versions:
        if v.get("status") == "withdrawn":
            continue
        for category, descriptor in (v.get("descriptors") or {}).items():
            if isinstance(descriptor, (list, tuple)) and len(descriptor) > 1:
                out.append(Finding(
                    "stacked_conditionals", ADVISORY, f"{v['node_version_id']}:{category}",
                    f"category {category} stacks {len(descriptor)} conditional judgments in one "
                    f"cell. Two raters can score the same paper on different clauses — split it, "
                    f"or expect misfit that cannot be diagnosed from the estimates."))
    return out


def check_grade_band_coherence(r: Registry) -> list[Finding]:
    """A node whose grade band disagrees with the task's.

    Cosmetic-looking and not: under the identity rule the grade band is part of the key the linking
    design rests on, so a mis-stated one is a wrong value in a load-bearing field. The crosswalk
    found a rubric headed '9th-12th Grade' on an 11-12 module.
    """
    node_by_id = {n["node_id"]: n for n in r.nodes}
    site_by_id = {s["site_id"]: s for s in r.sites}
    task_by_id = {t["task_id"]: t for t in r.tasks}
    out = []
    for sn in r.site_nodes:
        site = site_by_id.get(sn["site_id"])
        node = node_by_id.get(sn["node_id"])
        if not site or not node:
            continue
        task = task_by_id.get(site["task_id"])
        if not task or not task.get("grade_band"):
            continue
        if node.get("grade_band") != task["grade_band"]:
            out.append(Finding(
                "grade_band_coherence", ADVISORY, node["node_id"],
                f"node is banded {node.get('grade_band')!r} but task {task['task_id']} is "
                f"{task['grade_band']!r}. Grade band is part of the node identity, so this is a "
                f"wrong value in a key the linking design uses, not a display detail."))
    return out


def check_rubric_has_traits(r: Registry) -> list[Finding]:
    """A published rubric with no traits cannot score anything.

    It is not a harmless empty container: a scoring site pointing at it resolves to an empty trait
    set, and an artifact scored on nothing reaches `scored` with no observations at all — a paper
    that looks processed and measured nobody.
    """
    used = {t["rubric_id"] for t in r.rubric_traits}
    return [Finding("rubric_has_traits", BLOCKING, rb["rubric_id"],
                    f"rubric {rb.get('name')!r} is {rb.get('status')} and has no traits — a site "
                    f"pointing at it would score an artifact on nothing.")
            for rb in r.rubrics
            if rb.get("status") == "published" and rb["rubric_id"] not in used]


def check_rubric_trait_grade_band(r: Registry) -> list[Finding]:
    """A trait's grade band is part of its identity, so it cannot differ from its rubric's.

    If an 11-12 trait appears in a 6-8 rubric, one of the two is wrong and no amount of downstream
    care recovers which. Blocking, because it is decidable without judgment.
    """
    band = {n["node_id"]: n.get("grade_band") for n in r.nodes}
    rband = {rb["rubric_id"]: rb.get("grade_band") for rb in r.rubrics}
    out = []
    for t in r.rubric_traits:
        nb, rb = band.get(t["node_id"]), rband.get(t["rubric_id"])
        if nb and rb and nb != rb:
            out.append(Finding(
                "rubric_trait_grade_band", BLOCKING, t["node_id"],
                f"trait is grade band {nb} but rubric {t['rubric_id']} is {rb}. The band is part "
                f"of the trait's identity — one of the two is wrong."))
    return out


def check_trait_crosses_standards(r: Registry) -> list[Finding]:
    """A trait used by rubrics assigned to skills under DIFFERENT standards.

    This is the one place the many-to-many earns its advisory. Reusing a trait identifier across
    rubrics is how commonality is declared, and a trait shared across standards may be exactly the
    anchor that links them onto one metric — deliberate and valuable. It may equally be somebody
    reaching for a trait that looked close enough.

    The linter cannot tell those apart, and neither can a rule. It can refuse to let the question
    go unasked, which is what the advisory class is for.
    """
    rubric_standard: dict[str, set[str]] = {}
    for sk in r.skills:
        if sk.get("rubric_id"):
            rubric_standard.setdefault(sk["rubric_id"], set()).add(sk.get("standard_code"))

    by_trait: dict[str, set[str]] = {}
    for t in r.rubric_traits:
        by_trait.setdefault(t["node_id"], set()).update(
            rubric_standard.get(t["rubric_id"], set()))

    return [Finding("trait_crosses_standards", ADVISORY, node_id,
                    f"used by rubrics assigned to {len(stds)} different standards "
                    f"({', '.join(sorted(s for s in stds if s))}). If that is an anchor, say so; "
                    f"if it is a trait that looked close enough, it is a construct error.")
            for node_id, stds in sorted(by_trait.items()) if len({s for s in stds if s}) > 1]


def check_skill_unscored(r: Registry) -> list[Finding]:
    """A skill with no rubric is taught and not measured.

    Legitimate and common — the review console says so outright. Advisory rather than silent,
    because the alternative is a coverage table that quietly counts it as covered.
    """
    return [Finding("skill_unscored", ADVISORY, sk["skill_id"],
                    f"{sk.get('standard_code')}{sk.get('sub_code') or ''} has no rubric, so "
                    f"nothing about it is measured.")
            for sk in r.skills if not sk.get("rubric_id")]


RULES = (
    check_identifier_integrity,
    check_rubric_has_traits,
    check_rubric_trait_grade_band,
    check_trait_crosses_standards,
    check_skill_unscored,
    check_scale_declared,
    check_strand_substitution,
    check_anchor_coverage,
    check_descriptor_change_acknowledged,
    check_taught_but_unscored,
    check_stacked_conditionals,
    check_grade_band_coherence,
)


def lint(r: Registry) -> list[Finding]:
    """Every finding, blocking first. Advisory findings already acknowledged are dropped."""
    found: list[Finding] = []
    for rule in RULES:
        found.extend(rule(r))
    found = [f for f in found
             if not (f.severity == ADVISORY and f"{f.rule}:{f.subject}" in r.acknowledgments)]
    return sorted(found, key=lambda f: (f.severity != BLOCKING, f.rule, f.subject))


def blocks_publication(findings: Iterable[Finding]) -> bool:
    return any(f.severity == BLOCKING for f in findings)
