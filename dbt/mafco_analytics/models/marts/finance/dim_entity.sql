-- dim_entity: one row per Entity member, with full ancestor breadcrumb.
--
-- consolidation_view / segment are convenience aliases (level_1_name / level_2_name):
-- under the ultimate root, level_1 splits the tree into THREE ALTERNATE, OVERLAPPING
-- consolidation views over the same underlying legal entities -- SOP (legal structure),
-- WEB_Segment (business-segment view), WEB_SEC_Consol (SEC consolidation view) -- plus
-- an INACTIVE branch. The same base entity (e.g. entity_id 7340032) shows up once under
-- each view it belongs to, with a different ancestor chain each time.
--
-- **entity_id is therefore NOT a unique key on this model** -- the grain is
-- (entity_id, consolidation_view). If you want one row per entity, filter to a single
-- consolidation_view first, e.g. `where consolidation_view = 'WEB_Segment'` for the
-- business-segment cut (that's what dim_entity_segment does for you).
--
-- level_2 only means "business segment" (CPG, FLAVORS, ROYAL_OAK, CORP) under the
-- WEB_Segment branch -- it means something else under SOP or WEB_SEC_Consol.
--
-- IMPORTANT: segment entities do not sum to the consolidated total. Each segment already
-- carries its own intercompany balances with other segments; those are eliminated only at
-- the top consolidation entity (e.g. WEB_Segment), which is why its own stored balance is
-- the number to use for "Total", not sum(segments). See fct_balance_sheet for the same note.

select
    member_id                  as entity_id,
    member_name                 as entity_code,
    member_description          as entity_description,
    aggregation,
    depth,
    is_leaf                     as is_leaf_entity,
    ancestor_id_path,
    ancestor_name_path,
    sort_path,
    level_1_name                as consolidation_view,
    level_2_name                as segment,
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
from {{ ref('int_entity_hierarchy') }}
