"""Fit one assignment's scores and persist what the model could not explain.

    python -m measurement.fit_run --section-id sec-1 --task-id task-1 --iteration final

A severity says a rater is harsh. Fit says whether the model describes what happened at all — and
its per-person form answers a question a teacher has: do this paper's scores hang together?

A paper scoring 3, 3, 3, 1, 3, 3, 3 across seven traits contains one response nobody expected.
That is worth a second look, not because the 1 is wrong but because something inconsistent
happened and no mean will show it.

## One scale per run, enforced

The rating scale model estimates thresholds between adjacent categories, and thresholds belong to
the scale. Fitting a 1-6 holistic trait beside a 1-3 element estimates a scale nobody used. This
groups the assignment's traits by scale and refuses any group that mixes them.

It also means holistic traits get no person fit: one holistic trait per paper is one observation
per person, and one observation has no residual. That is a fact about the design, not a gap — and
it is reported rather than passed over, because a teacher told "no unexpected scores" should not be
hearing "we never looked".

## What is deliberately NOT written

No flag, no threshold, no "review this one". The statistics are stored; deciding what counts as
too much misfit is a reading, and readings belong to whoever is answerable for them. Convention
puts outfit above 2.0 in the range where a response distorts a measure — the report says so and
does not act on it.
"""
from __future__ import annotations

import argparse
import json
import uuid
from collections import defaultdict

from sqlalchemy import text

from ._db import engine
from .mfrm import NotConnected, Observation, fit

TENANT = "public"

# Conventional reading, and only a reading. Above this, a response is far enough from what the
# model expected that it distorts the measure it contributes to.
DISTORTING_OUTFIT = 2.0

_SCORES = text("""
    SELECT a.artifact_id,
           e.node_id,
           n.scale_categories,
           e.level,
           e.scoring_configuration_id
      FROM score_event e
      JOIN artifact a      ON a.artifact_id = e.artifact_id
      JOIN registry_node n ON n.node_id     = e.node_id
     WHERE e.tenant_id  = :tenant
       AND e.section_id = :section_id
       AND e.task_id    = :task_id
       AND e.iteration  = :iteration
       AND e.status     = 'scored'
       AND e.level IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM score_event s
                        WHERE s.supersedes_event_id = e.event_id)
""")

_RUN = text("""
    INSERT INTO measurement_fit_run
        (run_id, section_id, task_id, iteration, scoring_configuration_id, scale_categories,
         node_ids, observations, persons, thresholds, iterations, converged, tenant_id)
    VALUES (:run_id, :section_id, :task_id, :iteration, :config_id,
            CAST(:scale AS jsonb), CAST(:nodes AS jsonb), :observations, :persons,
            CAST(:thresholds AS jsonb), :iterations, :converged, :tenant)
""")

_ELEMENT = text("""
    INSERT INTO measurement_fit_element
        (run_id, facet, element_id, measure, se, n, infit, outfit, extreme, tenant_id)
    VALUES (:run_id, :facet, :element_id, :measure, :se, :n, :infit, :outfit, :extreme, :tenant)
""")


def by_scale(rows: list[dict]) -> dict[tuple, list[dict]]:
    """Group scores by the scale their trait uses. Pure, so the refusal to mix scales can be
    checked without a database.

    Keyed by the categories themselves rather than by their length: a 1-3 scale and a 0-2 scale
    are both three categories and are not the same scale.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        cats = tuple(int(c) for c in (r["scale_categories"] or []))
        if len(cats) >= 2:
            groups[cats].append(r)
    return dict(groups)


def observations(rows: list[dict], cats: tuple) -> list[Observation]:
    """One rating each, as the estimator wants them.

    The PERSON is the artifact and the RATER is the trait. That is the reverse of how the corpus
    comparison uses these names, and it is deliberate: there, several raters scored one paper and
    the question was about the raters. Here one rater scored several traits, and the question is
    whether a paper's answers agree with each other — so the traits take the facet that gets
    estimated, and the paper is the person whose fit we read.
    """
    lo = cats[0]
    return [Observation(person=r["artifact_id"], rater=r["node_id"],
                        category=int(float(r["level"])) - lo)
            for r in rows]


def run_one(conn, *, section_id: str, task_id: str, iteration: str) -> list[dict]:
    rows = [dict(r) for r in conn.execute(
        _SCORES, {"tenant": TENANT, "section_id": section_id,
                  "task_id": task_id, "iteration": iteration}).mappings()]
    if not rows:
        return []

    configs = {r["scoring_configuration_id"] for r in rows}
    if len(configs) > 1:
        # Two raters inside one fit would estimate a rater that does not exist. The scoring pin
        # normally prevents this; if it is here, something wrote around it.
        raise SystemExit(
            f"{section_id}/{task_id}/{iteration} holds scores from {len(configs)} configurations "
            f"{sorted(configs)}. A fit over two raters describes neither.")
    config_id = configs.pop()

    out = []
    for cats, group in sorted(by_scale(rows).items()):
        nodes = sorted({r["node_id"] for r in group})
        persons = len({r["artifact_id"] for r in group})
        if len(nodes) < 2:
            # One trait per paper is one observation per person, and one observation has no
            # residual. Reported rather than skipped in silence.
            out.append({"scale": list(cats), "nodes": nodes, "persons": persons,
                        "skipped": "a person fit needs at least two traits on one scale"})
            continue

        obs = observations(group, cats)
        try:
            f = fit(obs, max_category=len(cats) - 1)
        except (NotConnected, ValueError, ZeroDivisionError) as exc:
            out.append({"scale": list(cats), "nodes": nodes, "persons": persons,
                        "skipped": str(exc)})
            continue

        run_id = str(uuid.uuid4())
        conn.execute(_RUN, {
            "run_id": run_id, "section_id": section_id, "task_id": task_id,
            "iteration": iteration, "config_id": config_id,
            "scale": json.dumps(list(cats)), "nodes": json.dumps(nodes),
            "observations": len(obs), "persons": persons,
            "thresholds": json.dumps([round(t, 6) for t in f.thresholds]),
            "iterations": f.iterations, "converged": f.converged, "tenant": TENANT})

        for facet, elements in (("person", f.persons), ("rater", f.raters)):
            for e in elements.values():
                conn.execute(_ELEMENT, {
                    "run_id": run_id, "facet": facet, "element_id": e.name,
                    # An extreme element has no measure and therefore no error. Both NULL
                    # together, which the table checks.
                    "measure": None if e.extreme else round(e.measure, 6),
                    "se": None if e.extreme else round(e.se, 6),
                    "n": e.n,
                    "infit": None if e.infit != e.infit else round(e.infit, 4),
                    "outfit": None if e.outfit != e.outfit else round(e.outfit, 4),
                    "extreme": e.extreme, "tenant": TENANT})

        flagged = sum(1 for e in f.persons.values()
                      if e.outfit == e.outfit and e.outfit > DISTORTING_OUTFIT)
        out.append({"run_id": run_id, "scale": list(cats), "nodes": len(nodes),
                    "persons": persons, "observations": len(obs),
                    "converged": f.converged,
                    "papers_above_outfit_2": flagged})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--section-id", required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--iteration", required=True)
    a = ap.parse_args()

    eng = engine()
    with eng.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": TENANT})
        result = run_one(conn, section_id=a.section_id, task_id=a.task_id,
                         iteration=a.iteration)

    if not result:
        raise SystemExit("no scored papers for that assignment — nothing to fit.")
    print(json.dumps({"assignment": [a.section_id, a.task_id, a.iteration],
                      "groups": result,
                      "note": (f"outfit above {DISTORTING_OUTFIT} is the conventional reading of "
                               f"a response that distorts its measure. Stored, not acted on.")},
                     indent=1))


if __name__ == "__main__":
    main()
