-- fct_income_statement_detail: flat, pivotable Income Statement facts -- one row
-- per (entity, account, district, cost_center, IC partner, origin, data_type,
-- scenario, period), NOT aggregated the way fct_income_statement is.
--
-- This is a companion to fct_income_statement, not a replacement. Build reports
-- and validated headline numbers off fct_income_statement -- that's the model
-- we've reconciled against real OneStream exports line by line. Use THIS model
-- when someone needs to pivot/slice/investigate below the account level (by
-- cost center, by district, by intercompany partner, or to see whether a number
-- came from a raw import vs. a manual adjustment).
--
-- Two deliberate scope decisions, both worth knowing before you build on this:
--
-- 1. EVERY dimension is retained (District, CostCenter, IC, Origin, DataType),
--    not a trimmed-down subset. Each of these has already proven useful for
--    real investigation in this project -- CostCenter is literally how
--    OneStream's own official reports split COGS from SG&A (the same natural
--    account, e.g. Salaries, posts under both), Origin distinguishes a raw
--    import from an elimination or manual adjustment, IC maps directly to
--    intercompany trading-partner entities. Row count stays modest (this whole
--    company's raw facts export is ~159K rows for one period), so there's no
--    real cost to keeping them.
--
-- 2. NOT period-delta'd -- amount here is YTD-cumulative, same as raw EndBalLoad,
--    unlike fct_income_statement's LAG-based period-over-period calculation.
--    Deliberate: computing a period delta at THIS finer grain has a real
--    correctness risk that hasn't been validated -- e.g. a cost center with
--    activity in February but none in January would hit the "no prior
--    period" fallback path even though the entity/account itself has history,
--    misrepresenting a mid-year gap as day-one activity. Validating that
--    properly needs the same kind of exact-match-against-a-real-export check
--    the entity-level fix got, and there's no official cost-center-level
--    export to check against yet. In the meantime: this is a completely normal
--    thing to compute in a pivot table once time_period is a column (this
--    period vs. last period), so there's little value in pre-building it
--    ahead of an actual validated need.
--
-- Sign-flip IS applied (revenue adds, everything else subtracts) -- that part
-- is a simple per-account property, safe at any grain, unlike the period delta.

with facts as (

    select *
    from {{ ref('int_facts_usd') }}
    where flow_name = 'EndBalLoad'
      and data_type_name <> 'CFStmt_Calc'
      and amount_usd is not null

),

is_accounts as (

    select account_id, account_code, account_description, statement_type,
           depth, ancestor_id_path, sort_path,
           case when left(account_code, 1) = '4' then 1 else -1 end as rollup_sign
    from {{ ref('dim_account') }}
    where statement_type = 'IS'
      and is_leaf_account

)

select
    f.entity_id,
    f.entity_name       as entity_code,
    f.entity_description,
    f.account_id,
    a.account_code,
    a.account_description,
    a.depth              as account_depth,
    a.ancestor_id_path    as account_ancestor_id_path,
    a.sort_path           as account_sort_path,
    f.district_id,
    f.district_name,
    f.cost_center_id,
    f.cost_center_name,
    f.ic                  as intercompany_partner_code,
    f.origin,
    f.data_type_name,
    f.scenario_id,
    f.scenario_name,
    f.time_period,
    f.currency            as source_currency,
    f.amount_usd * a.rollup_sign as amount,   -- YTD-cumulative, sign-corrected -- see note above
    f._source_file,
    f._ingested_at
from facts f
inner join is_accounts a on a.account_id = f.account_id
