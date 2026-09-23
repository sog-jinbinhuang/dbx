-- fct_balance_sheet: period-end balance, one row per (entity, account, period, scenario).
--
-- Business rules baked in here (see the workbook review this replaces for the full rationale):
--   * flow_name = 'EndBalLoad'      -> the period-end balance (for IS accounts, which reset
--                                      each period, this is also the period's activity).
--   * data_type_name <> 'CFStmt_Calc' -> excludes the supplemental cash-flow sub-schedule,
--                                      which restates cash beginning/ending balances that are
--                                      already captured under Local_TB/Local_Adj/etc. Including
--                                      it would double-count cash.
--   * All remaining data_type_name members (Local_TB, Local_Adj, Manual_Input, Calculations)
--                                      ARE summed together -- they are additive layers of the
--                                      same balance (ledger + adjustments + manual + top-side),
--                                      not alternates. Verified: this sum balances Assets =
--                                      Liabilities + Equity exactly, for every entity.
--   * Filtered to statement_type = 'BS' via dim_account. Swap to 'IS' for a P&L fact table --
--     the same model shape works, just note IS accounts have no beginning balance concept.
--
-- IMPORTANT -- read before summing across entity_id:
--   Facts are stored at every level of the entity hierarchy that OneStream calculates a
--   consolidation for (base legal entities in local currency, translated/consolidated parent
--   entities in USD). Summing entity_id blindly double- or triple-counts. Either:
--     (a) pick ONE entity_id (or a set of sibling entity_ids) that doesn't include any of
--         their own ancestors/descendants also present in your selection, or
--     (b) join dim_entity_segment (or dim_entity filtered to one consolidation_view) and
--         use is_leaf_entity / ancestor_id_path to enforce that.
--   Segment entities (e.g. CPG, FLAVORS, ROYAL_OAK, CORP) do NOT sum to their parent
--   consolidation entity (e.g. WEB_Segment) -- intercompany positions between segments are
--   eliminated only at the parent. Pull the parent's own row for a true consolidated total
--   rather than summing its children.
--
-- This model deliberately does NOT join dim_entity for descriptive attributes: dim_entity's
-- grain is (entity_id, consolidation_view) -- see the note there -- and joining it in here on
-- entity_id alone would silently fan out every row 2-3x. entity_code/entity_description are
-- taken from stg_onestream__facts instead, which carries one value per entity_id already.
-- Join dim_entity_segment (or dim_entity filtered to your chosen consolidation_view) onto
-- entity_id downstream, in Python, once you've decided which view you need.
--
-- Sums amount_usd (from int_facts_usd), not the raw local-currency amount. For USD-native
-- entities this is identical to amount. For non-USD entities (individual local subsidiaries
-- like Argentina, Thailand, etc.) it's translated via fxrates' AverageRate_Fcst -- see
-- int_facts_usd.sql for the two known, accepted caveats (forecast not actual; average rate
-- used in place of a closing rate that doesn't exist for 2026). Pre-computed OneStream
-- consolidation entities (segment roots, _CONS nodes) are unaffected either way -- they're
-- already stored in USD by OneStream itself and pass through amount_usd = amount.
-- amount_usd is null wherever fx_conversion_missing is true (no matching rate found at
-- all) -- excluded here via the not-null filter rather than silently summed as zero.

with facts as (

    select *
    from {{ ref('int_facts_usd') }}
    where flow_name = 'EndBalLoad'
      and data_type_name <> 'CFStmt_Calc'
      and amount_usd is not null

),

bs_accounts as (

    select account_id, account_code, account_description, bs_section,
           depth, ancestor_id_path, sort_path
    from {{ ref('dim_account') }}
    where statement_type = 'BS'
      and is_leaf_account

),

aggregated as (

    select
        f.entity_id,
        max(f.entity_name)        as entity_code,        -- constant per entity_id; max() is just a group-safe pick
        max(f.entity_description) as entity_description,
        f.account_id,
        f.scenario_id,
        f.scenario_name,
        f.time_period,
        max(f.currency)           as currency,
        sum(f.amount_usd)         as amount
    from facts f
    inner join bs_accounts a on a.account_id = f.account_id
    group by f.entity_id, f.account_id, f.scenario_id, f.scenario_name, f.time_period

)

select
    agg.entity_id,
    agg.entity_code,
    agg.entity_description,
    agg.account_id,
    a.account_code,
    a.account_description,
    a.bs_section,
    a.depth        as account_depth,
    a.ancestor_id_path as account_ancestor_id_path,
    a.sort_path    as account_sort_path,
    agg.scenario_id,
    agg.scenario_name,
    agg.time_period,
    agg.currency,
    agg.amount
from aggregated agg
inner join bs_accounts a on a.account_id = agg.account_id
