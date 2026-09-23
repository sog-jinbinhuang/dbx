-- fct_income_statement: period activity, one row per (entity, account, period, scenario).
--
-- Mirrors fct_balance_sheet's flow/data-type filtering and entity double-counting
-- warning, but needs two additional corrections specific to Income Statement
-- accounts -- both found by reconciling against real OneStream "by entity" P&L
-- exports (BS accounts don't have either problem):
--
-- 1. SIGN: raw amounts are stored in "natural" sign, not report-ready sign.
--    Revenue (account codes starting with '4') should be ADDED; everything else
--    on the IS (COGS, SG&A, Interest, Other -- codes starting with '5'/'6'/'8')
--    should be SUBTRACTED. Confirmed empirically: summing everything with no sign
--    correction overstated Net Income by ~4.7x for a real entity (adding expenses
--    instead of subtracting them); applying this rule brought it to within <1%
--    of the official figure, with the small remainder traced to six specific
--    accounts individually explainable as ordinary business adjustments, not a
--    systematic error. dim_account's `aggregation` column does NOT capture this
--    -- it's +1 uniformly across the entire IS subtree -- so the sign has to be
--    derived here from account_code. This is a confirmed, not inferred, rule for
--    this chart of accounts (no separate Account Type property exists to use
--    instead) -- if a future segment/entity turns out to use a different numbering
--    convention, this CASE expression is the one place to extend.
--
-- 2. YTD vs PERIOD: flow_name = 'EndBalLoad' on an IS account is CUMULATIVE
--    year-to-date, not that period's standalone activity, despite IS accounts
--    conceptually "resetting" each year -- confirmed by matching our raw M2 value
--    exactly against an official YTD-labeled OneStream report, and separately
--    confirming Jan + Feb-only(per OneStream) = our M2 raw value to the cent.
--    True period activity = EndBalLoad(this period) - EndBalLoad(prior period).
--    Implemented as a LAG() window function below so it activates automatically
--    once more than one time_period is loaded. With only one period loaded (the
--    current state), LAG returns null (coalesced to 0), so amount = the
--    YTD-cumulative-through-that-period figure -- which is the most complete
--    figure obtainable until a prior period is ingested, not a bug.
--
-- Sums amount_usd (from int_facts_usd), not the raw local-currency amount -- same
-- FX handling as fct_balance_sheet, see int_facts_usd.sql for the two accepted
-- caveats (forecast rate, not actual; and note P&L conventionally uses an average
-- rate anyway, so AverageRate_Fcst is at least the methodologically right TYPE of
-- rate here, unlike for Balance Sheet). The sign flip (rollup_sign) is applied to
-- amount_usd, not raw amount -- order doesn't matter since it's a constant
-- per-account multiplier, but amount_usd must exist first either way.

with facts as (

    select *
    from {{ ref('int_facts_usd') }}
    where flow_name = 'EndBalLoad'
      and data_type_name <> 'CFStmt_Calc'
      and amount_usd is not null

),

is_accounts as (

    select account_id, account_code, account_description,
           depth, ancestor_id_path, sort_path,
           -- Revenue (starts with '4') adds; COGS/SG&A/Interest/Other subtracts.
           case when left(account_code, 1) = '4' then 1 else -1 end as rollup_sign
    from {{ ref('dim_account') }}
    where statement_type = 'IS'
      and is_leaf_account

),

aggregated_ytd as (

    select
        f.entity_id,
        max(f.entity_name)        as entity_code,
        max(f.entity_description) as entity_description,
        f.account_id,
        f.scenario_id,
        f.scenario_name,
        f.time_period,
        max(f.currency)           as currency,
        -- sort key for time_period so LAG orders chronologically even past month 9
        -- (time_period is text like '2026M2' -- lexical order breaks at '2026M10')
        cast(regexp_extract(f.time_period, '([0-9]+)M([0-9]+)', 1) as int) * 100
            + cast(regexp_extract(f.time_period, '([0-9]+)M([0-9]+)', 2) as int) as period_sort_key,
        sum(f.amount_usd * a.rollup_sign) as ytd_amount
    from facts f
    inner join is_accounts a on a.account_id = f.account_id
    group by f.entity_id, f.account_id, f.scenario_id, f.scenario_name, f.time_period

),

period_activity as (

    select
        *,
        ytd_amount - coalesce(
            lag(ytd_amount) over (
                partition by entity_id, account_id, scenario_id
                order by period_sort_key
            ), 0
        ) as amount
    from aggregated_ytd

)

select
    pa.entity_id,
    pa.entity_code,
    pa.entity_description,
    pa.account_id,
    a.account_code,
    a.account_description,
    a.depth        as account_depth,
    a.ancestor_id_path as account_ancestor_id_path,
    a.sort_path    as account_sort_path,
    pa.scenario_id,
    pa.scenario_name,
    pa.time_period,
    pa.currency,
    pa.amount
from period_activity pa
inner join is_accounts a on a.account_id = pa.account_id
