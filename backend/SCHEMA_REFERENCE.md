# Schema Reference (generated)

_Auto-generated from the SQLAlchemy models by `backend/scripts/gen_schema_reference.py` — do not edit by hand._

Documents the **as-built** database. The conceptual design is in [`../California/docs/TARGET_SCHEMA.md`](../California/docs/TARGET_SCHEMA.md).

## `dim_date` — public reference

| Column | Type | Constraints |
|---|---|---|
| `date_key` | TEXT | PK, NOT NULL |
| `school_year` | TEXT |  |
| `month` | SMALLINT |  |
| `iso_week` | SMALLINT |  |
| `day_of_week` | SMALLINT |  |
| `is_weekend` | BOOLEAN |  |

## `dim_instrument` — public reference

| Column | Type | Constraints |
|---|---|---|
| `instrument_id` | TEXT | PK, NOT NULL |
| `vendor` | TEXT |  |
| `display_name` | TEXT |  |
| `scale_type` | TEXT |  |
| `scale_min` | NUMERIC |  |
| `scale_max` | NUMERIC |  |
| `version` | TEXT |  |
| `notes` | TEXT |  |

## `dim_metric` — public reference

| Column | Type | Constraints |
|---|---|---|
| `metric_id` | TEXT | PK, NOT NULL |
| `domain` | TEXT |  |
| `display_name` | TEXT |  |
| `unit` | TEXT |  |
| `direction` | TEXT |  |
| `grains` | TEXT |  |
| `applies_to_levels` | TEXT |  |
| `applies_to_grades` | TEXT |  |
| `is_leading_indicator` | BOOLEAN |  |
| `data_origin` | TEXT |  |
| `instrument_dependent` | BOOLEAN |  |
| `definition` | TEXT |  |
| `suppress_threshold` | SMALLINT | default `11` |

## `dim_metric_relationship` — public reference

| Column | Type | Constraints |
|---|---|---|
| `leading_metric_id` | TEXT | PK, NOT NULL |
| `lagging_metric_id` | TEXT | PK, NOT NULL |
| `strength` | NUMERIC |  |

## `dim_peer_group` — public reference

| Column | Type | Constraints |
|---|---|---|
| `peer_group_id` | TEXT | PK, NOT NULL |
| `method` | TEXT |  |
| `school_level` | TEXT |  |
| `enroll_band` | TEXT |  |
| `sed_quartile` | SMALLINT |  |
| `locale_class` | TEXT |  |
| `n_schools` | INTEGER |  |

## `dim_period` — private (RLS)

| Column | Type | Constraints |
|---|---|---|
| `period_id` | TEXT | PK, NOT NULL |
| `grain` | TEXT |  |
| `school_year` | TEXT |  |
| `label` | TEXT |  |
| `start_date` | DATE |  |
| `end_date` | DATE |  |
| `day_in_session_start` | INTEGER |  |
| `day_in_session_end` | INTEGER |  |
| `sort_order` | INTEGER |  |
| `is_current` | BOOLEAN |  |
| `tenant_id` | TEXT | NOT NULL, FK→`dim_tenant.tenant_id`, default `public` |
| `visibility` | TEXT | NOT NULL, default `public` |

## `dim_school` — public reference

| Column | Type | Constraints |
|---|---|---|
| `school_id` | TEXT | PK, NOT NULL |
| `district_id` | TEXT |  |
| `state_school_id` | TEXT |  |
| `state_district_id` | TEXT |  |
| `school_year` | TEXT |  |
| `school_name` | TEXT |  |
| `district_name` | TEXT |  |
| `county_name` | TEXT |  |
| `school_level` | TEXT |  |
| `grade_low` | TEXT |  |
| `grade_high` | TEXT |  |
| `is_charter` | BOOLEAN |  |
| `is_title_i` | BOOLEAN |  |
| `is_dass` | BOOLEAN |  |
| `locale` | TEXT |  |
| `enroll_total` | INTEGER |  |
| `pct_sed` | NUMERIC |  |
| `pct_el` | NUMERIC |  |
| `pct_swd` | NUMERIC |  |
| `latitude` | NUMERIC |  |
| `longitude` | NUMERIC |  |
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
| `jurisdiction` | TEXT |  |

## `fact_metric` — private (RLS)

| Column | Type | Constraints |
|---|---|---|
| `school_id` | TEXT | PK, NOT NULL, FK→`dim_school.school_id` |
| `period_id` | TEXT | PK, NOT NULL, FK→`dim_period.period_id` |
| `metric_id` | TEXT | PK, NOT NULL, FK→`dim_metric.metric_id` |
| `student_group_id` | TEXT | PK, NOT NULL, FK→`dim_student_group.student_group_id` |
| `value` | NUMERIC |  |
| `value_status` | TEXT |  |
| `n_size` | INTEGER |  |
| `is_suppressed` | BOOLEAN |  |
| `is_unmapped` | BOOLEAN |  |
| `instrument_id` | TEXT |  |
| `source_dataset` | TEXT |  |
| `value_state` | NUMERIC |  |
| `value_district` | NUMERIC |  |
| `value_peer_median` | NUMERIC |  |
| `value_prior` | NUMERIC |  |
| `value_all_group` | NUMERIC |  |
| `target_value` | NUMERIC |  |
| `change` | NUMERIC |  |
| `change_3yr_slope` | NUMERIC |  |
| `series_break` | BOOLEAN |  |
| `gap_vs_state` | NUMERIC |  |
| `gap_vs_peer` | NUMERIC |  |
| `gap_vs_all_students` | NUMERIC |  |
| `z_in_peer` | NUMERIC |  |
| `pctile_in_peer` | NUMERIC |  |
| `status_level` | TEXT |  |
| `change_level` | TEXT |  |
| `band` | TEXT |  |
| `tenant_id` | TEXT | NOT NULL, FK→`dim_tenant.tenant_id`, default `public` |
| `visibility` | TEXT | NOT NULL, default `public` |

## `group_crosswalk` — public reference

| Column | Type | Constraints |
|---|---|---|
| `source_system` | TEXT | PK, NOT NULL |
| `source_code` | TEXT | PK, NOT NULL |
| `student_group_id` | TEXT |  |

## `plan` — private (RLS)

| Column | Type | Constraints |
|---|---|---|
| `plan_id` | TEXT | PK, NOT NULL |
| `school_id` | TEXT |  |
| `plan_year` | TEXT |  |
| `plan_type` | TEXT |  |
| `status` | TEXT |  |
| `adopted_date` | DATE |  |
| `total_budget` | NUMERIC |  |
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
| `entity_id` | TEXT | PK, NOT NULL |
| `period_id` | TEXT | PK, NOT NULL |
| `metric_id` | TEXT | PK, NOT NULL |
| `student_group_id` | TEXT | PK, NOT NULL |
| `value` | NUMERIC |  |
| `n_size` | INTEGER |  |

## `tenant_membership` — public reference

| Column | Type | Constraints |
|---|---|---|
| `tenant_id` | TEXT | PK, NOT NULL |
| `parent_id` | TEXT | PK, NOT NULL |

## `tenant_scope` — public reference

| Column | Type | Constraints |
|---|---|---|
| `tenant_id` | TEXT | PK, NOT NULL |
| `school_id` | TEXT | PK, NOT NULL |
