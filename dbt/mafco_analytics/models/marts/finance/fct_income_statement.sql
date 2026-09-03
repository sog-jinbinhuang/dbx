-- fct_income_statement: period activity, one row per (entity, account, period, scenario).
--
-- Mirrors fct_balance_sheet -- same flow/data-type filtering logic, same entity
-- double-counting warning, different statement_type filter. One key difference:
--
--   IS accounts have no beginning balance (they reset to zero each period), so
--   flow_name = 'EndBalLoad' on an IS account IS the period's activity -- not a
--   point-in-time balance the way it is for BS accounts. No further adjustment
--   needed, just don't read "EndBalLoad" as implying a cumulative balance here.
--
-- Unlike fct_balance_sheet, there's no bs_section-equivalent column. The IS subtree
-- is one long chain (IS -> NI -> Inc_before_NonControl_Int -> ... -> Op_Inc -> ...)
-- before it actually branches into Revenue vs COGS vs Opex, several levels deeper
-- than the BS's two-way Assets/Liab_and_Equity split -- there's no single depth that
-- gives a meaningful section label the way depth 3 does for BS. Use dim_account's
-- level_0..level_13 breadcrumb columns directly if you need a category cut.

with facts as (

    select *
    from {{ ref('stg_onestream__facts') }}
    where flow_name = 'EndBalLoad'
      and data_type_name <> 'CFStmt_Calc'

),

is_accounts as (

    select account_id, account_code, account_description,
           depth, ancestor_id_path, sort_path
    from {{ ref('dim_account') }}
    where statement_type = 'IS'
      and is_leaf_account

),

aggregated as (

    select
        f.entity_id,
        max(f.entity_name)        as entity_code,
        max(f.entity_description) as entity_description,
        f.account_id,
        f.scenario_id,
        f.scenario_name,
        f.time_period,
        max(f.currency)           as currency,
        sum(f.amount)             as amount
    from facts f
    inner join is_accounts a on a.account_id = f.account_id
    group by f.entity_id, f.account_id, f.scenario_id, f.scenario_name, f.time_period

)

select
    agg.entity_id,
    agg.entity_code,
    agg.entity_description,
    agg.account_id,
    a.account_code,
    a.account_description,
    a.depth        as account_depth,
    a.ancestor_id_path as account_ancestor_id_path,
    a.sort_path    as account_sort_path,
    agg.scenario_id,
    agg.scenario_name,
    agg.time_period,
    agg.currency,
    agg.amount
from aggregated agg
inner join is_accounts a on a.account_id = agg.account_id
