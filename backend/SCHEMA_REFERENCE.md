# Schema Reference (generated)

_Auto-generated from the SQLAlchemy models by `backend/scripts/gen_schema_reference.py` — do not edit by hand._

Documents the **as-built** database. The conceptual design is in [`../California/docs/TARGET_SCHEMA.md`](../California/docs/TARGET_SCHEMA.md).

## `dim_metric` — public reference

| Column | Type | Constraints |
|---|---|---|
| `metric_id` | TEXT | PK, NOT NULL |
| `domain` | TEXT |  |
| `display_name` | TEXT |  |
| `unit` | TEXT |  |
| `direction` | TEXT |  |
| `applies_to_levels` | TEXT |  |
| `applies_to_grades` | TEXT |  |
| `is_leading_indicator` | BOOLEAN |  |
| `cadence` | TEXT |  |
| `source_dataset` | TEXT |  |
| `data_origin` | TEXT |  |
| `instrument_dependent` | BOOLEAN |  |
| `definition` | TEXT |  |
| `suppress_threshold` | SMALLINT | default `11` |

## `dim_school` — public reference

| Column | Type | Constraints |
|---|---|---|
| `school_cds` | TEXT | PK, NOT NULL |
| `school_year` | TEXT | PK, NOT NULL |
| `school_name` | TEXT |  |
| `district_cds` | TEXT |  |
| `district_name` | TEXT |  |
| `county_name` | TEXT |  |
| `school_level` | TEXT |  |
| `grade_low` | TEXT |  |
| `grade_high` | TEXT |  |
| `is_charter` | BOOLEAN |  |
| `enroll_total` | INTEGER |  |
| `peer_group_id` | TEXT |  |

## `dim_student_group` — public reference

| Column | Type | Constraints |
|---|---|---|
| `student_group_id` | TEXT | PK, NOT NULL |
| `label` | TEXT |  |
| `dimension` | TEXT |  |
| `is_equity_focus` | BOOLEAN |  |

## `dim_tenant` — public reference

| Column | Type | Constraints |
|---|---|---|
| `tenant_id` | TEXT | PK, NOT NULL |
| `tenant_type` | TEXT |  |
| `display_name` | TEXT |  |
| `cds_prefix` | TEXT |  |
| `jurisdiction` | TEXT | default `CA` |

## `fact_metric` — private (RLS)

| Column | Type | Constraints |
|---|---|---|
| `school_cds` | TEXT | PK, NOT NULL, FK→`dim_school.school_cds` |
| `school_year` | TEXT | PK, NOT NULL, FK→`dim_school.school_year` |
| `metric_id` | TEXT | PK, NOT NULL, FK→`dim_metric.metric_id` |
| `student_group_id` | TEXT | PK, NOT NULL, FK→`dim_student_group.student_group_id` |
| `value` | NUMERIC |  |
| `value_status` | TEXT |  |
| `n_size` | INTEGER |  |
| `is_suppressed` | BOOLEAN |  |
| `is_unmapped` | BOOLEAN |  |
| `instrument_id` | TEXT |  |
| `period` | TEXT |  |
| `value_state` | NUMERIC |  |
| `value_district` | NUMERIC |  |
| `value_peer_median` | NUMERIC |  |
| `value_prior` | NUMERIC |  |
| `target_value` | NUMERIC |  |
| `change` | NUMERIC |  |
| `gap_vs_state` | NUMERIC |  |
| `gap_vs_peer` | NUMERIC |  |
| `gap_vs_all_students` | NUMERIC |  |
| `z_in_peer` | NUMERIC |  |
| `pctile_in_peer` | NUMERIC |  |
| `series_break` | BOOLEAN |  |
| `status_level` | TEXT |  |
| `change_level` | TEXT |  |
| `dashboard_color` | TEXT |  |
| `tenant_id` | TEXT | NOT NULL, FK→`dim_tenant.tenant_id`, default `public` |
| `visibility` | TEXT | NOT NULL, default `public` |

## `plan` — private (RLS)

| Column | Type | Constraints |
|---|---|---|
| `plan_id` | TEXT | PK, NOT NULL |
| `school_cds` | TEXT |  |
| `plan_year` | TEXT |  |
| `plan_type` | TEXT |  |
| `status` | TEXT |  |
| `adopted_date` | DATE |  |
| `total_budget` | NUMERIC |  |
| `funding_sources` | TEXT |  |
| `source_url` | TEXT |  |
| `tenant_id` | TEXT | NOT NULL, FK→`dim_tenant.tenant_id`, default `public` |
| `visibility` | TEXT | NOT NULL, default `public` |

## `plan_action` — private (RLS)

| Column | Type | Constraints |
|---|---|---|
| `action_id` | TEXT | PK, NOT NULL |
| `goal_id` | TEXT | NOT NULL, FK→`plan_goal.goal_id` |
| `strategy_text` | TEXT |  |
| `category_id` | TEXT |  |
| `target_metric_id` | TEXT |  |
| `target_group_id` | TEXT |  |
| `budgeted_amount` | NUMERIC |  |
| `funding_source_id` | TEXT |  |
| `fte` | NUMERIC |  |
| `role_type` | TEXT |  |
| `is_district_provided` | BOOLEAN |  |
| `owner` | TEXT |  |
| `tenant_id` | TEXT | NOT NULL, FK→`dim_tenant.tenant_id`, default `public` |
| `visibility` | TEXT | NOT NULL, default `public` |

## `plan_goal` — private (RLS)

| Column | Type | Constraints |
|---|---|---|
| `goal_id` | TEXT | PK, NOT NULL |
| `plan_id` | TEXT | NOT NULL, FK→`plan.plan_id` |
| `lcff_priority` | SMALLINT |  |
| `linked_metric_id` | TEXT |  |
| `target_group_id` | TEXT |  |
| `baseline_value` | NUMERIC |  |
| `baseline_year` | TEXT |  |
| `target_value` | NUMERIC |  |
| `target_year` | TEXT |  |
| `prior_status` | TEXT |  |
| `narrative` | TEXT |  |
| `tenant_id` | TEXT | NOT NULL, FK→`dim_tenant.tenant_id`, default `public` |
| `visibility` | TEXT | NOT NULL, default `public` |

## `ref_benchmark` — public reference

| Column | Type | Constraints |
|---|---|---|
| `level` | TEXT | PK, NOT NULL |
| `entity_cds` | TEXT | PK, NOT NULL |
| `school_year` | TEXT | PK, NOT NULL |
| `metric_id` | TEXT | PK, NOT NULL |
| `student_group_id` | TEXT | PK, NOT NULL |
| `value` | NUMERIC |  |
| `n_size` | INTEGER |  |
