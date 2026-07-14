# School Classification ("Schools Like You") — Concept

*School Improvement Plans prototype · MVP · July 2026*
*The idea. Companion to `school-classification-lit-review.md` (the evidence) and
`school-classification-spec.md` (the build). This document establishes **why**.*

---

## 1. The problem it solves

Every school-data product answers "how is this school doing?" the same way: it puts the
school's number next to the **state average**. That comparison is quietly unfair, and
everyone in a school building knows it. A Title-I high school where 80% of students are
economically disadvantaged and a third are English learners is not usefully compared to
"California." Its leaders already know they're below the state line; being told so again
is noise. The question they actually ask is: *"compared to schools that look like mine, are
we ahead or behind — and what are the ones ahead of us doing?"*

Answering that requires a **fair reference set**: the set of schools that start from the
same place. Not the same test scores — the same *inputs*. Poverty, language, disability,
size, community type. Give a school its input-matched peers and its own numbers change
meaning: a chronic-absenteeism rate that looks alarming against the state can be middle-of-
the-pack against similar schools — or, more usefully, *worse* than peers who face the same
headwinds, which is the finding that actually drives action.

"Schools Like You" is the engine that produces that reference set, once, for every school
in the country, from public federal data.

---

## 2. The concept in one line

> For any school, compute the ~50 most **demographically similar** schools of the same
> instructional level — matched on inputs, never on outcomes — and use that peer set as the
> yardstick everything else is read against.

Three words carry the whole idea:

- **Similar** — a real multivariate distance (Mahalanobis over standardized demographic
  features), so correlated inputs like poverty / EL / minority don't triple-count. Not a
  hand-tuned index, not a bucket someone drew on a map.
- **Inputs, not outcomes** — the match vector contains only the conditions a school is dealt
  (who walks in the door), never how it performs. This is the non-negotiable that makes the
  comparison honest; §4 explains why.
- **Every school gets its own set** — fixed-count nearest neighbors, not hard clusters. Each
  school sits at the center of its own band of 50 peers, so no school lands in a lopsided
  group of 9 or 134. (Clustering does exactly that; the literature is unambiguous.)

---

## 3. What it unlocks — and why it matters *here*

This platform already extracts, structures, and serves what schools **plan to do** — the
SPSA goals, funded strategies, budgets, and verbatim plan language, alongside each school's
real indicators (the attendance mart is the first working slice). Peer groups turn that from
a lookup into an argument.

**Today, without peers:** *"Wilson High's chronic absenteeism is 35%."* True, and inert. Is
that bad? Bad for whom? What should they do?

**With peers:** *"Wilson's chronic absenteeism is 35% — 71st percentile among its 50 most
similar high schools, so higher than most schools facing the same demographics. Here are the
five most-similar schools that are beating it on attendance, and here is what their plans
fund that Wilson's does not."*

That last sentence is the product. It only exists when two things the platform already has —
**indicators** and **extracted plans** — are read through a **fair peer set**. Peer grouping
is the connective tissue that makes the plan-comparison work we've built *meaningful*:

- **Benchmarking that lands.** "Below state" is dismissible; "behind schools exactly like
  you" is not. The peer percentile is the number that gets a room's attention.
- **Plan comparison with a defensible frame.** "Copy what the top districts do" is noise.
  "Here's what your true peers who outperform you are funding" is a lead. Peers scope the
  comparison to strategies that plausibly transfer.
- **Finding the bright spots.** The schools worth learning from aren't the highest-scoring
  ones (they may just enroll advantaged students) — they're the ones outperforming *their*
  peers. Peer groups are how you locate them.

Peer grouping isn't a feature bolted onto the platform. It's the lens that makes the rest of
the platform say something a superintendent can act on.

---

## 4. The principles that make it trustworthy

A peer engine is only as good as the discipline behind it. Four principles, each a load-
bearing decision (the spec traces them to the evidence):

1. **Match on inputs, never outcomes.** If test scores enter the distance metric, the model
   quietly learns "schools like you *are supposed to* score like this" — it launders the very
   inequity it should expose. Outcomes are physically kept out of the matching component; the
   only place peers and indicators meet is the serving view. This is enforced in the
   architecture, not just the policy.

2. **The peer bar is never the ceiling.** The most dangerous failure mode is implying "good
   for a school like this" is good enough — soft bigotry of low expectations, encoded in a
   dashboard. Every peer-relative number is served **beside an absolute one** (the fixed
   proficiency / attendance bar), so "75th percentile among your peers" and "still below the
   state standard" always appear together. Peers contextualize; they don't excuse.

3. **Race is shown, not matched (by default).** Matching *on* race normalizes racialized gaps
   — it would treat a segregated peer set as the fair comparison. Race/ethnicity is displayed
   across the peer group but excluded from the distance vector; flipping that is a deliberate,
   logged config choice, not an accident of the schema.

4. **Public data → public artifact, fully reproducible.** Similarity is computed from the
   public federal universe (CCD / EDFacts), so the peer lists are identical for every user and
   carry no tenant boundary — they live cleanly on the public side of the isolation seam. Only
   the *indicator values shown across* a peer group are tenant-private. Every run persists its
   partition statistics, so any peer list can be reproduced exactly and audited.

These aren't hedges. They're what separates a credible improvement tool from a ranking that
tells advantaged schools they're fine and everyone else that they're doomed.

---

## 5. What the user experiences

The engine is invisible; two capabilities surface:

- **"Show me schools like this one."** A ranked, honest peer set — with a low-confidence flag
  when the match is genuinely loose (a thin or unusual school), because a weak match is
  labeled, never hidden.
- **"How am I doing versus schools like me — and what are they doing differently?"** The
  target's value, its percentile within its peer set, the peer distribution, the absolute
  standard beside it, and — the payoff — the *plans* of the peers who outperform it.

In the conversational surface we've already built, this reads as: ask "who's like Wilson and
who's beating them on attendance?" and get a grounded, cited answer that names real peers,
real rates, and real funded strategies.

---

## 6. Scope of the concept, and what it is *not*

The MVP concept is deliberately narrow: **a rigorous, reproducible input-matching engine on
public data, serving fair peer sets**. That is the hard, valuable, reusable core.

It is explicitly **not**, for MVP: a live "like X but also filter Y" query engine, a
multi-year stability model, a community-context (ACS/Census) enrichment, or an empirically
tuned peer count. Those are real improvements, and they're real deferrals — the point of the
narrow scope is to get the *matching discipline* right first, because everything downstream
(benchmarks, plan comparison, bright-spot finding) inherits its integrity.

The **build** — feature model, Mahalanobis mechanics, the mart tables, the batch job, the
serving guardrail — is fully specified in [`school-classification-spec.md`](./school-classification-spec.md).
The **evidence** for every design direction is in the companion lit review. This document is
just the case for *why it belongs at the center of the platform*.

---

## 7. Where it sits

Peer groups are a **public reference mart** derived from the federal reference layer,
alongside the star schema — see the platform's [`ARCHITECTURE.md`](../../ARCHITECTURE.md) for
the five-layer model and the public/private seam. They compute once per federal data release
and serve as a cheap indexed lookup, so the inference layer stays fast and deterministic. The
`dim_school` dimension already carries the input features this needs (economic disadvantage,
EL, disability, enrollment, locale, level), keyed on the NCES id — the same identity the rest
of the platform now uses. The engine reads what's already there and writes the peer lists
back as public data.

---

## Companion documents

- `school-classification-lit-review.md` — the evidence base (why input-matching, why
  Mahalanobis, why fixed-count peers, the equity cautions).
- [`school-classification-spec.md`](./school-classification-spec.md) — the build (features,
  distance computation, mart DDL, batch job, serving layer).
- [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) — platform context (layers, tenancy, the
  public/private seam this artifact sits on the public side of).
