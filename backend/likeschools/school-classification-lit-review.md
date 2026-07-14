# Classifying Public Schools for Improvement: A Literature Review of Demographic-Based "Schools Like You" Peer Grouping

*Prepared for the School Improvement Plans prototype · July 2026*

---

## Executive summary

The question this review addresses is narrow and practical: **how should a system decide which schools count as "like" a given school**, when the purpose is school improvement and the design principle is equity? The consistent answer across the US policy literature and the most-cited international models is that peer groups should be built from **demographic and contextual inputs** — who the students are and where the school sits — and *not* from the school's own results. Matching on inputs holds student context roughly constant so that the remaining differences in outcomes are the part plausibly within a school's control. Matching on outcomes does the opposite: it defines "similar" as "scoring the same," which makes any relative-performance comparison circular.

The single most directly on-point source is the US Institute of Education Sciences / Regional Educational Laboratory (REL) Central *Guide to Identifying Similar Schools to Support School Improvement*. It lays out a replicable methodology — pick input variables, standardize them, compute a statistical distance between every pair of schools, and assign each school a fixed number of nearest neighbors — and it states explicitly that outcome data such as proficiency or graduation rates should be **excluded** from the distance calculation when the goal is to evaluate relative performance. Operating US and international systems follow the same shape: California's former Academic Performance Index (API) "Similar Schools Rank" (100 peers off a School Characteristics Index), Texas's 40-campus comparison groups, Nebraska's 27-variable matched-peer model, Australia's ICSEA-based "statistically similar schools" groups (up to 60 neighbors), and England's "Families of Schools" (a weighted composite index feeding a nearest-neighbor assignment).

The methodological consensus favors a **weighted composite index feeding a fixed-count nearest-neighbor match** over hard clustering that partitions all schools into discrete buckets, because clustering produces wildly uneven group sizes (New Mexico's implementation yielded a largest group of 134 schools and a smallest of 9) whereas nearest-neighbor gives every school the same number of comparators. Whichever is chosen, **standardizing every variable before computing distance is non-negotiable** — otherwise a variable measured in raw counts (enrollment) swamps one measured as a proportion (percent English learners).

The critiques are real but, in the verified evidence gathered here, more theoretical than empirically settled. The chief equity worry is that demographic benchmarking can institutionalize *lower expectations* for schools serving disadvantaged students ("the soft bigotry of low expectations"). A subtler and well-founded concern is **endogeneity in weight construction**: several real systems derived the *weights* that combine demographic inputs by regressing those inputs against test outcomes — so outcomes quietly shape the index even when they never enter an individual school's score. This is the design trap most worth avoiding in a new build. The review closes with concrete implementation guidance: variable set, public data sources (CCD, EDFacts, ACS-derived NCES locale), a recommended nearest-neighbor approach, and the open question of how many peers to assign.

> **A note on evidence strength.** The rationale, the variable sets, the operating models, the statistical methods, and the data sources below rest on primary sources (federal guides, state technical documentation, national statistical agencies) that were adversarially verified. The *critiques* section is weaker: little primary empirical evidence on the specific harms survived verification, so those cautions are presented as well-reasoned design risks rather than established findings, and are flagged as such.

---

## 1. Framing: what "classification for improvement" means, and why inputs

"Classification of schools" can mean several different things, and it is worth separating them because they serve different masters:

- **Accountability identification** — sorting schools into intervention tiers (e.g., ESSA's Comprehensive, Targeted, and Additional Targeted Support). This is deliberately **outcomes-based**: a school is identified because its results or subgroup results fall below a threshold.
- **Descriptive typology** — stable structural categories such as grade span (elementary/middle/high) or NCES urban-centric locale (city/suburb/town/rural). These are **input/contextual** and change slowly.
- **Peer grouping ("schools like you")** — assembling, for each school, a set of comparable schools so that its performance can be read against a fair reference set rather than against the state as a whole. This is the target of this review, and the literature is close to unanimous that the *matching* should be done on **inputs**, precisely so that the *comparison* can be about outcomes.

The logic is worth stating carefully because it is the whole equity argument. If you want to ask "is this school doing well *given who it serves*?", you must first define a comparison group that resembles it on the things it does not control — student poverty, language, disability, mobility, community context. If instead you build the comparison group using results, you have defined peers as schools that already perform alike, and the question "are they performing differently?" answers itself. The IES/REL guide makes this explicit: including current outcomes in the distance measure is inappropriate when the goal is relative-performance evaluation, because it matches schools on the very thing you are trying to compare.

**Implications for the feature.** The prototype should treat "peer grouping" as a distinct function from any accountability label. The peer-group engine consumes *only* input/contextual variables. If the product later surfaces outcomes (proficiency, growth, graduation), those live on the *comparison* side of the UI — shown across the peer group — never inside the similarity computation. Bake this separation into the data model now: an `inputs` feature vector used for matching, and an `outcomes` set used only for display and ranking within a group.

---

## 2. The equity rationale: similar students, different results

The empirical premise behind input-based grouping is that **demographics constrain but do not determine outcomes** — schools serving near-identical populations produce markedly different results, and that spread is where improvement lives.

The canonical demonstration is EdSource's California study *Similar Students, Different Results* (2005–2006). To hold demographics roughly constant, the researchers drew a sample of 257 elementary schools from a narrow band (the 25th–35th percentile) of California's **School Characteristics Index (SCI)** — an input-based composite of parent education, student mobility, low-income status, English-learner percentage, and ethnicity. Despite near-identical demographic profiles (median 78% free/reduced-price lunch), these schools' Growth API scores varied by roughly **250 points**. The study's whole design depends on an input-based similarity index: only by first defining "similar students" demographically could it isolate and then investigate "different results."

This is the affirmative case for the approach. Its mirror image is the IES guide's warning in Section 1: if you had instead grouped those 257 schools by their API scores, you would have manufactured similarity in outcomes and destroyed the ability to see the 250-point spread at all.

**Implications for the feature.** The value proposition of "schools like you" is exactly the EdSource move, productized: put a school next to demographically-matched peers and let the outcome spread become visible and actionable. The narrative to a district user is "these schools face what you face — here is the range of what they achieve, and here are the ones pulling ahead." That framing is both the equity justification and the product hook. It also implies the peer group must be demographically *tight* enough that users find the comparison credible — a loose group invites the objection "those schools aren't really like us."

---

## 3. US federal frameworks: the backdrop and the building blocks

No single US federal system prescribes demographic peer grouping, but three federal structures set the context and supply the raw material.

**ESSA identification (the outcomes-based contrast).** Under the Every Student Succeeds Act, states identify schools for **Comprehensive Support and Improvement** (lowest ~5% of Title I schools, plus low-grad-rate high schools), **Targeted Support** (consistently underperforming subgroups), and **Additional Targeted Support**. This is the dominant federal "classification," and it is explicitly results-based. It matters here as the thing peer grouping is *not*: ESSA tells you a school is struggling; it does not tell you which schools are fair comparators. A "schools like you" feature is complementary — it gives an identified school a demographically honest reference set to learn from.

**NCES urban-centric locale codes (a ready-made contextual variable).** NCES classifies every school's location into four primary locale types — **City, Suburb, Town, Rural** — each split into three subtypes, for **12 codes**. The classification is built from Census Bureau urban/rural criteria, population-size thresholds, and measured distance to urbanized areas, plus OMB principal-city designations. Crucially, **no outcome metric enters it** — it is a pure geographic/demographic descriptor, and it collapses cleanly to a 4-category or urban/rural dichotomy when a coarser control is wanted.

**CCD and EDFacts (the data spine).** The **Common Core of Data (CCD)** is NCES's annual universe census of US public schools and districts, published since the early 1990s, carrying enrollment, race/ethnicity, grade span, free/reduced-price lunch counts, and (via its locale files) urbanicity. **EDFacts** adds school-level counts including economically-disadvantaged students (file specs FS033 for free/reduced-price lunch and FS226 for economically disadvantaged, both current in the SY 2024–25 specifications) and English-learner and special-education counts.

**Implications for the feature.** The federal layer hands the prototype almost everything it needs for free and at national scale: CCD + EDFacts + locale gives enrollment/size, grade span, race/ethnicity, FRPL/economic disadvantage, EL, special education, and urbanicity — a complete first-pass input vector with stable annual updates and a common school ID (NCES ID) to join on. Build the schema around the CCD school universe and treat EDFacts and the locale files as joins onto it.

---

## 4. US state "similar schools" models

State systems are where demographic peer grouping actually operates, and they converge on strikingly similar designs.

**California — API "Similar Schools Rank" (the reference implementation).** From the late 1990s to 2013, California published for each school both a statewide API decile and a **Similar Schools Rank (1–10)**. The similar-schools comparison worked off the **School Characteristics Index (SCI)**, a composite of demographic inputs (parent education, mobility, low-income, EL, ethnicity, and related factors). Each school was ranked on the SCI, and its comparison set was formed by taking the **50 schools immediately above and 50 immediately below** it on the SCI scale — a **100-school nearest-neighbor band**. The school's own API was then decile-ranked *within that band*. This is a clean, well-documented example of the composite-index-plus-nearest-neighbor pattern, and much of the later literature echoes it.

**Texas — TEA comparison groups.** The Texas Education Agency assigns each campus a group of the **40 most demographically similar campuses statewide**, matched on grade levels served, campus size, percent economically disadvantaged, student mobility rate, percent English learners, and percent receiving special-education services. Fixed group size (40) again reflects a nearest-neighbor rather than clustering design.

**Nebraska — REL Central matched peers.** In partnership with REL Central (the same body behind the IES guide), Nebraska built matched peer groups from **27 variables**, including NSLP eligibility, racial/ethnic minority percentage, homelessness, migrant and English-learner percentages, attendance, and graduation rate. Nebraska explicitly chose a **distance-based matching** approach over discrete clustering so that every school receives the *same number* of matched peers.

**Massachusetts — DART.** The DESE **District Analysis and Review Tools (DART)** let users track data over time and "make sound, meaningful comparisons to the state or to comparable organizations." DART confirms sustained official demand for peer comparison, though the public page does not disclose its exact matching methodology.

**New Mexico — a cautionary clustering example.** New Mexico used a discrete grouping method that, as the IES guide notes, produced **highly uneven group sizes — largest group 134 schools, smallest 9**. This is the concrete argument against hard clustering for this use case.

| System | Group construction | Size | Key input variables | Notes |
|---|---|---|---|---|
| **CA API Similar Schools** | Nearest-neighbor band on SCI composite | 100 (50 up / 50 down) | Parent ed., mobility, low-income, EL, ethnicity | Retired 2013; the classic reference design |
| **TX TEA comparison groups** | Fixed nearest-neighbor, statewide | 40 | Grade span, size, econ. disadv., mobility, EL, special ed. | Currently operating |
| **NE (REL Central)** | Statistical distance matching | Fixed per school | 27 vars incl. NSLP, minority %, homeless, migrant, EL, attendance | Chose distance over clustering deliberately |
| **MA DART** | Peer comparison (method not public) | — | — | Demonstrates official demand |
| **NM** | Discrete clustering | 9–134 (uneven) | — | Illustrates the clustering size problem |

**Implications for the feature.** The state models are a menu of validated defaults. California's 100-peer band and Texas's 40-campus set bracket a reasonable range for a nearest-neighbor `k`. The Texas variable set is a compact, implementable input vector that maps almost one-to-one onto CCD/EDFacts fields. And the New Mexico experience is the reason to prefer nearest-neighbor over k-means for the first version: users expect a school to always have "a group," and uneven cluster sizes (some schools with 8 peers, others with 130) read as arbitrary.

---

## 5. International reference models

Two international systems are the most methodologically instructive and are worth borrowing from directly.

**Australia — ICSEA and "statistically similar schools."** The Index of Community Socio-Educational Advantage (**ICSEA**) underpins the "similar schools" comparison on the national *My School* site. ICSEA is constructed as:

> **ICSEA = SEA (parental occupation + parental school and non-school education) + school Remoteness (ARIA) + percent Indigenous enrolment.**

It is emphatically **not** a measure of a school's achievement — ACARA states it is "not a rating of the school." On *My School*, each school is compared against a **Statistically Similar Schools Group (SSSG) of up to 60 schools** — the ~30 closest above and ~30 closest below on the ICSEA scale — a textbook nearest-neighbor band. One important historical wrinkle: in the 2009–2010 construction, the *weights* combining ICSEA's community inputs were derived by regressing 14 Census (SEIFA-derived) socio-economic variables against a NAPLAN-based performance factor. So the inputs are purely demographic, but the *scale's coefficients* were originally trained against outcomes — the endogeneity point revisited in Section 7. (Post-2011, ICSEA moved toward directly-collected parent occupation/education where available.)

**England — "Families of Schools" and IDACI.** England's *Families of Schools* model groups schools using four contextual/input variables combined into a weighted composite, then assigns each school to the family of schools with the closest overall score:

> prior attainment (average Key Stage 2 point score, **~66%**) + a deprivation measure combining **IDACI** and free-school-meals eligibility (**~20%**) + English as an additional language (**~10%**) + pupil mobility (**~4%**).

Note that "prior attainment" is an **intake** measure (what pupils bring on arrival), not the school's own output, so the model still avoids grading schools by their own results. **IDACI** (Income Deprivation Affecting Children Index) is a small-area deprivation index — the English analogue of using ACS/Census neighborhood poverty as a community-context variable. (Caveat: the verified evidence here comes from a single 2011 regional document, so treat the exact weights as illustrative rather than current national practice. England's related **Ofsted IDSR / "similar schools"** reporting sits in the same tradition but was not separately verified in this review.)

**Implications for the feature.** ICSEA and Families of Schools contribute two design ideas worth importing. First, a **community socio-economic context variable** derived from where students live (SEIFA in Australia, IDACI in England) — the US equivalent is ACS/Census block-group poverty or education attached via student geography or school location. This captures neighborhood disadvantage that a within-school FRPL rate alone misses. Second, the **up-to-60 nearest-neighbor band** (ICSEA) and the explicit weighted-composite formula (Families of Schools) are concrete, copyable templates. The cautionary lesson from ICSEA's history is Section 7's: if you derive weights, be deliberate about whether outcomes are allowed anywhere near that derivation.

---

## 6. The variable catalog: what goes into the input vector

Pooling the variables used across the models above yields a stable, recurring set. They fall into three tiers by how consistently they appear and how readily US public data supplies them.

**Tier 1 — near-universal, directly available (use these first).**

- **Economic disadvantage / FRPL** — the single most common variable; free/reduced-price lunch eligibility or an economically-disadvantaged count (CCD; EDFacts FS033/FS226).
- **English learners** — percent EL/ELL (CCD/EDFacts).
- **Students with disabilities / special education** — percent with IEPs (CCD/EDFacts).
- **Race/ethnicity** — percent by group, or a combined minority percentage (CCD).
- **School size** — total enrollment (CCD).
- **Grade span / level** — elementary/middle/high or served grades (CCD); often used as a hard filter rather than a distance dimension.
- **Urbanicity / locale** — NCES 4- or 12-category locale (CCD locale files).

**Tier 2 — common and valuable, sometimes harder to source cleanly.**

- **Student mobility** — churn/stability rate (used by Texas, Nebraska, Families of Schools; availability varies by state).
- **Community socio-economic context** — neighborhood poverty/education from ACS/Census (the US analogue of ICSEA's SEIFA and England's IDACI).
- **Homelessness and migrant status** — used by Nebraska (EDFacts carries both).

**Tier 3 — used abroad, weaker/indirect US availability.**

- **Parental occupation and education** — central to ICSEA and California's SCI, but not collected school-by-school in US federal data; must be **proxied** via ACS neighborhood educational-attainment and occupation data attached by geography.

**Implications for the feature.** Ship v1 on Tier 1 alone — it is complete, national, annually refreshed, and joinable on NCES ID. Treat grade span as a **hard partition** (never compare an elementary school to a high school) rather than a distance dimension. Fold in Tier 2 (especially an ACS community-poverty variable) as a fast follow, since neighborhood context materially sharpens "schools like you" credibility. Tier 3 is a proxy exercise — reach for it only if users report that Tier 1+2 groups feel too coarse. Decide explicitly whether **race/ethnicity** belongs in the *distance* metric or is reserved for *display*: it is demographically informative but politically and statistically fraught (Section 7), and several equity critics argue matching *on* race normalizes racialized outcome gaps.

---

## 7. Statistical methodology

There are four decisions to make, and the literature gives a clear default for each.

**(a) Composite index vs. raw multivariate distance.** Two equivalent-in-spirit routes exist: compute a single weighted **composite score** and match on that one number (California SCI, ICSEA, Families of Schools), or keep variables separate and compute a **multivariate distance** across all of them (IES guide, Nebraska). The composite route is simpler to explain ("schools near you on one index"); the multivariate route preserves more information and avoids collapsing distinct dimensions that shouldn't trade off against each other. Both are well-precedented.

**(b) Distance measure.** The IES guide contrasts **Euclidean distance** (straight-line distance on standardized variables) with **Mahalanobis distance** (which additionally accounts for correlation among variables, so two correlated inputs like FRPL and EL don't double-count). The matching literature (e.g., the MatchIt documentation) notes Mahalanobis-type covariate distance tends to produce closer matches across many covariates than propensity-score matching when the goal is tight similarity — which is exactly the "schools like you" goal.

**(c) Nearest-neighbor vs. hard clustering.** This is the pivotal choice. **Discrete clustering** (k-means, Ward's hierarchical, or two-stage hierarchical-then-k-means as in the SAS higher-ed peer example) partitions all schools into buckets — but bucket sizes vary enormously (New Mexico: 9 to 134), and a school near a cluster boundary can have very different "peers" from an almost-identical school just across the line. **Fixed-count nearest-neighbor** gives every school its own centered band of the same size (CA's 100, TX's 40, ICSEA's 60) and degrades gracefully. Nebraska chose distance-based matching specifically for this equal-peers property. For a "schools like you" product where each school is the center of its own view, nearest-neighbor is the natural fit; clustering is better suited to producing a small number of named school *types* for reporting.

**(d) Standardization — mandatory.** Every source that computes distance insists variables be **standardized** (e.g., z-scored) first. Unscaled, a variable with a large numeric range dominates: the geographic-data-science reference gives the vivid example that a one-dollar change in median house value can equal the entire 0–1 range of a proportion variable. Standardize before any distance or clustering step, without exception.

**Implications for the feature.** The recommended v1 pipeline: assemble the standardized Tier-1 input vector → compute pairwise **Mahalanobis (or standardized-Euclidean) distance** within grade-span partitions → assign each school its **k nearest neighbors**. Prefer nearest-neighbor over k-means for the primary "your peers" view; if the product also wants a small set of human-readable school *archetypes* (e.g., for filters or narrative), run a separate clustering pass for that display purpose only. Precompute distances offline and store each school's neighbor list — with ~100k US schools, an all-pairs distance within grade-span/locale partitions is tractable as a batch job.

---

## 8. Critiques, pitfalls, and cautions

This section is deliberately hedged: the affirmative literature above is well-sourced, but the critique literature was thinly represented in the verified evidence. The cautions below are well-reasoned design risks — several are logically airtight — but readers should not take them as empirically quantified here.

**The soft bigotry of low expectations.** The central equity critique of demographic benchmarking is that comparing disadvantaged schools only to other disadvantaged schools can normalize and entrench a lower standard — a school "doing well for schools like it" may still be failing its students against any absolute bar. Demographic peer grouping answers "well relative to whom?" but must never be allowed to answer "well enough."

**Endogeneity in weight construction (the most concrete trap).** This one is well-founded and specific. Although a school's *inputs* are demographic, several real systems derived the *weights* combining those inputs by regressing them against test outcomes — ICSEA's 2010 construction and California's SCI both did versions of this. When weights are trained on outcomes, outcomes leak into the similarity metric through the back door, partially reintroducing the circularity the input-based design was meant to avoid. A clean build either uses **transparent, non-outcome-derived weights** (equal weighting, or expert/policy-assigned weights) or is explicit that any outcome-derived weighting is a modeling choice with this known cost.

**Contextual measures can mask, not just reveal.** The scholarly critique of "contextual value-added" (associated with Gillborn & Youdell in the UK) argues that adjusting or benchmarking performance by demographic context can obscure genuine inequities — effectively excusing weaker outcomes for marginalized groups by folding their disadvantage into the expectation. Matching **on race/ethnicity** is the sharpest version of this concern: it can normalize racialized achievement gaps rather than surface them. (Flagged as under-verified: the primary source for this critique did not survive this review's verification, but the argument is prominent in the field.)

**Stability over time.** Demographic-based groups shift as enrollments change year to year; a school's peer set churning annually undermines the longitudinal comparisons users most want. None of the verified sources quantified year-over-year stability — an open empirical question (Section 9).

**Small-n schools.** For very small schools, demographic percentages are noisy (one student can move a subgroup percentage several points), making their matches unstable. Small schools need either wider bands, minimum-denominator rules, or explicit "low-confidence match" flags.

**Gaming.** Where demographic reporting drives consequential comparisons, there is an incentive to report categories advantageously (e.g., economic-disadvantage or EL classification). This is more a governance/data-integrity concern than a modeling one, but it argues for using audited federal counts rather than self-reported figures.

**Implications for the feature.** Turn each critique into a product guardrail. (1) **Always show an absolute reference alongside the peer comparison** — a school's standing against its peers *and* against a fixed proficiency/growth bar — so the tool never implies "good for a poor school" is the ceiling. (2) **Use transparent, non-outcome-derived weights** in v1; if you ever fit weights, disclose it and keep outcomes out of the fit. (3) **Make race a display dimension, not (by default) a matching dimension**, and let the design be defensible on that choice. (4) **Flag small-n and low-confidence matches** in the UI rather than presenting a shaky group as authoritative. (5) Source variables from **audited CCD/EDFacts counts**, not self-report, wherever possible.

---

## 9. Implementation blueprint for the prototype

Pulling the review together into a concrete recommendation for the "schools like you" engine:

**Data sources.** Backbone: **CCD** school universe (enrollment, grade span, race/ethnicity, FRPL, locale), joined on NCES school ID. Add **EDFacts** (FS033/FS226 economic disadvantage; EL; special education; homeless/migrant if wanted). Add **ACS/Census** (via NCES EDGE geography) for a neighborhood socio-economic context variable. This trio is public, national, annually refreshed, and needs no licensing — a clean fit for the prototype's public-reference-table layer described in `ARCHITECTURE.md`.

**Input vector (v1).** Standardized: percent economically disadvantaged, percent EL, percent special education, percent by race/ethnicity (or minority percent), enrollment (size), and NCES locale. **Grade span as a hard partition, not a distance dimension.** Add student mobility and an ACS community-poverty variable in v2.

**Method.** Standardize (z-score) every variable → compute **Mahalanobis or standardized-Euclidean distance** among schools within the same grade-span partition → assign each school its **k nearest neighbors**. Precompute and store neighbor lists as a batch job; refresh annually with each CCD release.

**How many peers (k)?** The operating precedents bracket the range: **Texas 40, Australia up to 60, California 100**. None of the sources establishes a statistically optimal number, so this is a genuine open design choice — a reasonable default is **~40–50**, large enough for a stable outcome distribution and small enough to feel "like us," with the value tunable and possibly widened for small-n or sparse-locale schools. Make `k` a configuration parameter, not a hard-coded constant.

**Keep outcomes out of the match.** Proficiency, growth, and graduation are computed and displayed *across* the peer group (that is the product's payoff), but they never enter the distance metric. Enforce this as an architectural boundary: a matching service that has no read access to the outcomes tables is the cleanest way to guarantee it.

**Governance guardrails.** Ship with (a) an absolute reference shown beside every peer comparison, (b) transparent non-outcome-derived weights, (c) race as display-by-default, and (d) explicit low-confidence flags for small-n schools.

---

## 10. Open questions the literature did not settle

- **Optimal `k` / minimum group size.** Precedents span 40–100 with no established optimum or reliability floor. Worth an internal sensitivity analysis on your own data.
- **What the harms literature actually establishes.** The masking/low-expectations, gaming, and contextual-measure critiques are prominent as arguments but were under-substantiated by primary empirical evidence in this review. A dedicated pass on the critical scholarship (Gillborn & Youdell and successors) would firm this up.
- **Year-over-year stability.** How much do demographic peer groups churn annually, and should the design smooth them (e.g., multi-year averaged inputs) to keep longitudinal comparisons coherent?
- **Weighting philosophy.** Equal, expert-assigned, or empirically derived weights — and does any outcome-based derivation reintroduce the endogeneity the input-based approach exists to avoid? (The review's clear lean: avoid outcome-derived weights, or disclose them explicitly.)

---

## Sources

Primary and directly-cited sources verified in this review:

- IES / REL Central, *A Guide to Identifying Similar Schools to Support School Improvement* — https://ies.ed.gov/use-work/resource-library/resource/other-resource/guide-identifying-similar-schools-support-school-improvement and full text https://files.eric.ed.gov/fulltext/ED613435.pdf ; announcement blog https://ies.ed.gov/learn/blog/new-guide-outlines-approach-identifying-similar-schools-support-school-improvement
- EdSource, *Similar Students, Different Results: Why Do Some Schools Do Better?* (California; School Characteristics Index study) — https://promiseofplace.org/research-evaluation/research-and-evaluation/similar-students-different-results-why-do-some-schools
- California Academic Performance Index & Similar Schools Rank (School Characteristics Index / 100-school band) — https://en.wikipedia.org/wiki/Academic_Performance_Index_(California_public_schools) ; https://www.ed-data.org/article/Understanding-the-Academic-Performance-Index-(API) ; http://www.mikemcmahon.info/apisimilar.htm
- NCES urban-centric locale codes — https://nces.ed.gov/programs/edge/Geographic/LocaleBoundaries ; classification methodology https://nces.ed.gov/programs/edge/docs/LOCALE_CLASSIFICATIONS.pdf
- NCES Common Core of Data (CCD) overview — https://nces.ed.gov/ccd/pub_overview.asp
- US ED EDFacts file specifications, SY 2024–25 (FS033, FS226) — https://www.ed.gov/data/edfacts-initiative/edfacts-resources/edfacts-file-specifications/edfacts-file-specifications-sy-2024-25 ; ED Data Express https://eddataexpress.ed.gov/download
- Massachusetts DESE, District Analysis and Review Tools (DART) — https://www.doe.mass.edu/dart/
- Australia ACARA, *Guide to Understanding ICSEA Values* — https://docs.acara.edu.au/resources/Guide_to_understanding_ICSEA_values.pdf ; ICSEA technical paper (2010) — https://www.darcymoore.net/wp-content/uploads/2010/01/my20school20icsea20technical20paper2020091020.pdf
- England DfE, *Families of Schools* (Black Country secondary, 2011; IDACI + KS2 + EAL + mobility weighting) — https://assets.publishing.service.gov.uk/media/5a8167b540f0b62302697205/Families_fo_schools_2011_Black_Country_secondary_schoolspdf.pdf
- Methodology references: standardization before clustering — https://geographicdata.science/book/notebooks/10_clustering_and_regionalization.html ; Mahalanobis vs. propensity matching (MatchIt) — https://cran.r-project.org/web/packages/MatchIt/vignettes/matching-methods.html ; two-stage hierarchical + k-means peer grouping (SAS) — https://support.sas.com/resources/papers/proceedings14/1279-2014.pdf

Under-verified / directional (critique literature, use with caution):

- Gillborn & Youdell, *Equity, ethnicity and the hidden dangers of 'contextual' measures of school performance*, Race Ethnicity and Education (2010) — https://www.tandfonline.com/doi/abs/10.1080/13613324.2010.543388 *(cited but did not survive this review's source verification; representative of the critical scholarship)*
- TES, on contextual value-added and accountability — https://www.tes.com/magazine/archive/contextual-value-added-might-not-be-holy-grail-when-it-comes-holding-schools-account
