-- dim_entity_segment: dim_entity filtered down to the WEB_Segment consolidation branch only.
-- Unique on entity_id (unlike dim_entity, which has one row per entity per consolidation
-- view it appears under). Use this when you want a single business-segment label per entity,
-- e.g. joining onto fct_balance_sheet for a "Balance Sheet by Segment" report.
--
-- Carries depth + level_0..level_11 breadcrumbs (same shape as dim_account) so you can
-- derive parent/child relationships within this branch generically -- e.g. finding the
-- direct-child entities of a segment (level_2_id = the segment's own entity_id, at
-- depth = 3) for a "companies below CPG" drill-down, the same way dim_account's
-- breadcrumbs support walking down from a Balance Sheet section into individual accounts.

select
    entity_id,
    entity_code,
    entity_description,
    segment,               -- 'CPG' | 'FLAVORS' | 'ROYAL_OAK' | 'CORP' | 'IC_Holding'
    ancestor_name_path,
    is_leaf_entity,
    depth,
    level_0_id,  level_0_name,
    level_1_id,  level_1_name,
    level_2_id,  level_2_name,
    level_3_id,  level_3_name,
    level_4_id,  level_4_name,
    level_5_id,  level_5_name,
    level_6_id,  level_6_name,
    level_7_id,  level_7_name,
    level_8_id,  level_8_name,
    level_9_id,  level_9_name,
    level_10_id, level_10_name,
    level_11_id, level_11_name
from {{ ref('dim_entity') }}
where consolidation_view = 'WEB_Segment'
