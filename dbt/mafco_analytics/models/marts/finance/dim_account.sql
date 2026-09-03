-- dim_account: one row per Account member, with full ancestor breadcrumb.
--
-- statement_type / bs_section are convenience aliases, not hardcoded IDs: they read off
-- level_2_name / level_3_name because, in this chart of accounts, Top(0) > Trial_Balance(1)
-- > BS|IS(2) > Assets|Liab_and_Equity|NI(3). If OneStream ever restructures the top of the
-- account tree, these two columns will need to point at different levels -- the underlying
-- level_0..level_13 breadcrumb columns are untouched by that and always reflect the live tree.

select
    member_id                  as account_id,
    member_name                 as account_code,
    member_description          as account_description,
    aggregation,
    depth,
    is_leaf                     as is_leaf_account,
    ancestor_id_path,
    ancestor_name_path,
    sort_path,
    level_2_name                as statement_type,   -- 'BS' | 'IS' | 'Alloc_and_Assess' | 'Suspense' | ...
    level_3_name                as bs_section,        -- 'Assets' | 'Liab_and_Equity' (BS only) | 'NI' (IS only)
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
    level_11_id, level_11_name,
    level_12_id, level_12_name,
    level_13_id, level_13_name
from {{ ref('int_account_hierarchy') }}
