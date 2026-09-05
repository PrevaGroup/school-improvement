-- What a scoring run actually wrote. Read-only; safe against a live database.
--
--   psql "host=127.0.0.1 dbname=sip user=sip_migrator" -f sql/22_scoring_run_report.sql 1>&2
--
-- The smoke test proves the invariants hold. This shows what the pipeline DID — which is a
-- different question, and the one that tells you whether the thing is any good rather than
-- whether it is correct. A pipeline can be flawlessly correct and produce useless scores.
--
-- The number to look at first is the verification drop rate. It is the deterministic gate's
-- yield, and it is the only per-run figure that says something about the model rather than about
-- the code: spans proposed, spans that were actually in the paper, and the gap between them.

\pset border 2
\timing off

\echo ''
\echo '=== artifacts and where they got to ==='
SELECT a.artifact_id, a.state, a.iteration, a.window_label,
       count(e.event_id) AS events,
       count(*) FILTER (WHERE e.status = 'scored')               AS scored,
       count(*) FILTER (WHERE e.status = 'abstained')            AS abstained,
       count(*) FILTER (WHERE e.status = 'no_verified_evidence') AS no_evidence
  FROM artifact a
  LEFT JOIN score_event e ON e.artifact_id = a.artifact_id
 GROUP BY a.artifact_id, a.state, a.iteration, a.window_label
 ORDER BY a.artifact_id;

\echo ''
\echo '=== every state change, and who made it ==='
SELECT artifact_id, from_state, to_state, actor_type, actor_id,
       to_char(created_at, 'HH24:MI:SS') AS at
  FROM artifact_state_transition
 ORDER BY artifact_id, created_at;

\echo ''
\echo '=== the scores ==='
SELECT e.artifact_id, e.node_id, n.criterion_label, e.status, e.level, e.confidence,
       (e.evidence->>'proposed')::int              AS proposed,
       jsonb_array_length(e.evidence->'kept')      AS kept,
       jsonb_array_length(e.evidence->'dropped')   AS dropped
  FROM score_event e
  LEFT JOIN registry_node n ON n.node_id = e.node_id
 ORDER BY e.artifact_id, e.node_id;

\echo ''
\echo '=== the verification gate: what the model proposed vs what was actually in the paper ==='
SELECT sum((evidence->>'proposed')::int)            AS spans_proposed,
       sum(jsonb_array_length(evidence->'kept'))    AS verified,
       sum(jsonb_array_length(evidence->'dropped')) AS dropped,
       round(100.0 * sum(jsonb_array_length(evidence->'dropped'))
             / nullif(sum((evidence->>'proposed')::int), 0), 1) AS drop_pct
  FROM score_event;

\echo ''
\echo '=== what was dropped, in full — the fabrications the gate caught ==='
SELECT e.artifact_id, e.node_id, d->>'span' AS proposed_but_not_in_the_paper
  FROM score_event e, jsonb_array_elements(e.evidence->'dropped') d
 ORDER BY e.artifact_id, e.node_id;

\echo ''
\echo '=== the facet stamp: one rater, named, on every event ==='
SELECT scoring_configuration_id, scorer_type, scorer_id, trait_set_version,
       scrutiny_passes, count(*) AS events,
       count(DISTINCT rubric_version) AS rubric_versions,
       count(*) FILTER (WHERE form_variant IS NOT NULL) AS with_form_variant
  FROM score_event
 GROUP BY 1,2,3,4,5;

\echo ''
\echo '=== the configuration pin: exactly one rater per section x task x iteration ==='
SELECT section_id, task_id, iteration,
       count(DISTINCT scoring_configuration_id) AS configurations,
       string_agg(DISTINCT scoring_configuration_id, ', ') AS which
  FROM score_event
 WHERE scorer_type = 'ai'
 GROUP BY 1,2,3;

\echo ''
\echo '=== calibration membership: proposed only for scored outcomes on a measurement occasion ==='
SELECT is_measurement_occasion, status, enters_calibration, count(*)
  FROM score_event
 GROUP BY 1,2,3
 ORDER BY 1,2;

\echo ''
\echo '=== idempotency: one observation per (artifact, node, rater, pass) ==='
SELECT count(*) AS events, count(DISTINCT idempotency_key) AS distinct_keys,
       CASE WHEN count(*) = count(DISTINCT idempotency_key)
            THEN 'ok — no doubled observations'
            ELSE 'FAIL — a resumed run doubled something' END AS verdict
  FROM score_event;

\echo ''
\echo '=== the review packet: what a teacher would be shown ==='
SELECT c.artifact_id, c.composer_version, c.needs_human, c.prior_rater_mismatch,
       jsonb_array_length(c.packet->'criteria')                       AS criteria,
       (SELECT count(*) FROM jsonb_array_elements(c.packet->'criteria') x
         WHERE jsonb_array_length(x->'prior') > 0)                    AS with_prior,
       c.packet->>'prior_note'                                        AS qualification
  FROM artifact_composition c
 ORDER BY c.artifact_id;

\echo ''
\echo '=== no dropped span reaches the packet as evidence ==='
SELECT CASE WHEN count(*) = 0
            THEN 'ok — every span shown to a teacher survived verification'
            ELSE 'FAIL — ' || count(*) || ' fabricated span(s) reached a packet' END AS verdict
  FROM artifact_composition c,
       jsonb_array_elements(c.packet->'criteria') crit,
       jsonb_array_elements_text(crit->'evidence') shown,
       score_event e,
       jsonb_array_elements(e.evidence->'dropped') d
 WHERE e.artifact_id = c.artifact_id
   AND e.node_id = crit->>'node_id'
   AND shown = d->>'span';

\echo ''
\echo '=== a level exists if and only if the status is scored ==='
SELECT CASE WHEN count(*) = 0 THEN 'ok — no level without a score, no score without a level'
            ELSE 'FAIL — ' || count(*) || ' row(s) violate it' END AS verdict
  FROM score_event
 WHERE (status = 'scored') <> (level IS NOT NULL);
