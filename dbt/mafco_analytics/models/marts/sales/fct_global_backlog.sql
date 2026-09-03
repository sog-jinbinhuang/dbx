with

-- ── Date parameters: derived automatically from current_date() ──────────
-- Databricks SQL warehouses default their session timezone to UTC, while
-- this pipeline ran in America/New_York on Snowflake. Plain current_date()
-- shifts every period bucket (cur_month, cur_qtr, next_month, ...) forward
-- whenever UTC has already rolled past midnight local time -- most visibly
-- at month-end, when it silently bumps cur_month/cur_qtr into next month.
-- Computing "today" once from an explicit NY conversion keeps every
-- downstream bucket correct regardless of the warehouse's default timezone.
today as (
    select cast(from_utc_timestamp(current_timestamp(), 'America/New_York') as date) as ny_today
),

params as (
    select
        year(ny_today)                                            as cy,
        year(ny_today) - 1                                        as py,
        month(ny_today)                                           as cur_month,
        quarter(ny_today)                                         as cur_qtr,
        IF(month(ny_today) = 12, 1,
            month(ny_today) + 1)                                  as next_month,
        IF(month(ny_today) = 12,
            year(ny_today) + 1,
            year(ny_today))                                       as nm_cy
    from today
),

-- ── Dimension: customers ──────────────────────────────────────────────────
-- Deduplicate STG_CUST so each (database, cust_code) key appears once.
-- All null/blank fallbacks applied here; downstream CTEs use clean values.
dim_cust as (
    select database, cust_code, cust_name, cust_group, sales_rep
    from (
        select
            upper(trim(source_database))                                as database,
            nullif(trim(cust_code), '')                                 as cust_code,
            coalesce(nullif(trim(cust_name),            ''), 'UNKNOWN')       as cust_name,
            coalesce(nullif(trim(cust_group),           ''), 'NEW BUSINESS')  as cust_group,
            coalesce(nullif(trim(default_sales_agent_2),''), 'NEW BUSINESS')  as sales_rep,
            -- Databricks has no QUALIFY clause -- row_number + outer WHERE
            -- replicates the same "keep first row per key" behavior.
            -- Ordered on the post-coalesce alias to match Snowflake's QUALIFY
            -- semantics (which evaluate after the SELECT list is computed).
            row_number() over (
                partition by upper(trim(source_database)), trim(cust_code)
                order by coalesce(nullif(trim(cust_name), ''), 'UNKNOWN') nulls last
            ) as rn
        from {{ ref('stg_cust') }}
    )
    where rn = 1
),

-- ── Dimension: products ───────────────────────────────────────────────────
dim_product as (
    select database, product_code, product_name, product_division, reporting_segment
    from (
        select
            upper(trim(source_database))                                as database,
            nullif(trim(product_code), '')                              as product_code,
            coalesce(nullif(trim(product_name),     ''), '(No Product Master)') as product_name,
            upper(coalesce(nullif(trim(product_division),''),'NEW BUSINESS'))    as product_division,
            coalesce(nullif(trim(product_segment),  ''), 'NEW BUSINESS')         as reporting_segment,
            row_number() over (
                partition by upper(trim(source_database)), trim(product_code)
                order by coalesce(nullif(trim(product_name), ''), '(No Product Master)') nulls last
            ) as rn
        from {{ ref('stg_product') }}
    )
    where rn = 1
),

-- ── Sales fact: join dims, filter to years we need ────────────────────────
-- Only pulls years required for any period column or trend column.
-- Quarter is derived here so the pivot CTEs don't need to recompute it.
sales_enriched as (
    select
        upper(trim(f.database))                           as database,
        nullif(trim(f.cust_code),    '')                  as cust_code,
        nullif(trim(f.product_code), '')                  as product_code,
        cast(f.year  as int)                              as year,
        cast(f.month as int)                              as month,
        CAST(ceil(cast(f.month as int) / 3.0) AS INT)             as quarter,
        coalesce(f.revenue, 0)                            as revenue,

        -- dimension attributes
        coalesce(c.cust_group,  'NEW BUSINESS')           as cust_group,
        coalesce(c.sales_rep,   'NEW BUSINESS')           as sales_rep,
        coalesce(c.cust_name,   'UNKNOWN')                as cust_name,
        coalesce(p.reporting_segment, 'NEW BUSINESS')     as reporting_segment,
        coalesce(p.product_name,     '(No Product Master)') as product_name,
        coalesce(p.product_division, 'NEW BUSINESS')      as product_division,

        -- display label used by workbook
        coalesce(p.product_name, '(No Product Master)')
            || ' (' || trim(f.product_code) || ')'        as prod_label,

        -- params columns (available to the pivot below via cross join)
        p2.cy, p2.py, p2.cur_month, p2.cur_qtr,
        p2.next_month, p2.nm_cy

    from {{ ref('fct_global_sales_orders_2') }}  f
    cross join params p2
    left join dim_cust    c on c.database     = upper(trim(f.database))
                           and c.cust_code    = nullif(trim(f.cust_code), '')
    left join dim_product p on p.database     = upper(trim(f.database))
                           and p.product_code = nullif(trim(f.product_code), '')
    where f.invoice_date is not null
      -- only fetch years needed: CY, PY, NM_CY, NM_CY-1, and 5 trend years (CY-4+)
      and cast(f.year as int) between p2.cy - 4 and p2.nm_cy
),

-- ── Budget fact: join dims with explicit orphan handling ──────────────────
--
-- Cases handled:
--   A  cust_code + product_code both match dims           → clean, normal row
--   B  cust_code matches, product_code missing from dim   → is_no_product_master = true
--   C  cust_code missing from dim, product_code matches   → is_no_cust_master = true
--   D  both keys missing from dims                        → both flags true
--   E  cust_code is NULL / blank in source                → treated as Case C/D
--   F  product_code is NULL / blank in source             → treated as Case B/D
--
-- All cases are kept so budget dollars still flow into totals.
-- Flag columns surface orphaned rows for monitoring and dbt tests.
-- ─────────────────────────────────────────────────────────────────────────
budget_enriched as (
    select
        upper(trim(b.database))                           as database,

        -- Normalise keys: blank/whitespace treated as NULL so joins behave
        -- consistently regardless of how the source encodes missing values
        nullif(trim(b.cust_code),    '')                  as cust_code,
        nullif(trim(b.product_code), '')                  as product_code,

        cast(b.year      as int)                          as year,
        cast(b.month_num as int)                          as month,
        CAST(ceil(cast(b.month_num as int) / 3.0) AS INT)         as quarter,
        coalesce(b.budget_rev, 0)                         as budget_rev,

        -- Customer attributes: from stg_cust join only — fallback to NEW BUSINESS
        -- if cust_code is blank/null or not found in stg_cust
        coalesce(c.cust_group, 'NEW BUSINESS')            as cust_group,
        coalesce(c.sales_rep,  'NEW BUSINESS')            as sales_rep,
        coalesce(c.cust_name,  'UNKNOWN')                 as cust_name,

        -- Product attributes: from stg_product join only — fallback to NEW BUSINESS
        -- if product_code is blank/null or not found in stg_product
        coalesce(p.reporting_segment, 'NEW BUSINESS')     as reporting_segment,
        coalesce(p.product_name,     '(No Product Master)') as product_name,
        coalesce(p.product_division, 'NEW BUSINESS')      as product_division,

        -- Orphan flags: true means the dim join failed for this row
        (c.cust_code    is null)                          as is_no_cust_master,
        (p.product_code is null)                          as is_no_product_master,

        p2.cy, p2.cur_month, p2.cur_qtr,
        p2.next_month, p2.nm_cy

    from {{ ref('fct_budget') }}  b
    cross join params p2
    left join dim_cust    c
           on c.database  = upper(trim(b.database))
          and c.cust_code = nullif(trim(b.cust_code), '')
    left join dim_product p
           on p.database     = upper(trim(b.database))
          and p.product_code = nullif(trim(b.product_code), '')
    where cast(b.year as int) in (p2.cy, p2.nm_cy)
),

-- ── Aggregate sales to grain, pivot periods ───────────────────────────────
sales_agg as (
    select
        reporting_segment,
        cust_group,
        database,
        cust_code,
        product_code,

        -- CY actuals
        sum(case when year = cy  and month = cur_month   then revenue else 0 end) as cy_cur_month,
        sum(case when year = cy  and month <= cur_month  then revenue else 0 end) as cy_ytd,
        sum(case when year = cy  and quarter = cur_qtr   then revenue else 0 end) as cy_cur_qtr,
        sum(case when year = nm_cy and month = next_month then revenue else 0 end) as cy_next_month,
        sum(case when year = cy                           then revenue else 0 end) as cy_whole_year,

        -- PY actuals (same calendar periods, one year back)
        sum(case when year = cy - 1 and month = cur_month    then revenue else 0 end) as py_cur_month,
        sum(case when year = cy - 1 and month <= cur_month   then revenue else 0 end) as py_ytd,
        sum(case when year = cy - 1 and quarter = cur_qtr    then revenue else 0 end) as py_cur_qtr,
        sum(case when year = nm_cy - 1 and month = next_month then revenue else 0 end) as py_next_month,
        sum(case when year = cy - 1                           then revenue else 0 end) as py_whole_year,

        -- 5-year trend: whole-year actuals, CY-4 through CY
        sum(case when year = cy - 4 then revenue else 0 end) as trend_yr_4,
        sum(case when year = cy - 3 then revenue else 0 end) as trend_yr_3,
        sum(case when year = cy - 2 then revenue else 0 end) as trend_yr_2,
        sum(case when year = cy - 1 then revenue else 0 end) as trend_yr_1,
        sum(case when year = cy     then revenue else 0 end) as trend_yr_0

    from sales_enriched
    group by 1, 2, 3, 4, 5
),

-- ── Aggregate budget to grain, pivot periods ──────────────────────────────
budget_agg as (
    select
        reporting_segment,
        cust_group,
        database,
        cust_code,
        product_code,

        sum(case when year = cy    and month = cur_month    then budget_rev else 0 end) as bgt_cur_month,
        sum(case when year = cy    and month <= cur_month   then budget_rev else 0 end) as bgt_ytd,
        sum(case when year = cy    and quarter = cur_qtr    then budget_rev else 0 end) as bgt_cur_qtr,
        sum(case when year = nm_cy and month = next_month   then budget_rev else 0 end) as bgt_next_month,
        sum(case when year = cy                             then budget_rev else 0 end) as bgt_whole_year

    from budget_enriched
    group by 1, 2, 3, 4, 5
),

-- ── Budget orphan summary (diagnostic — for dbt tests / monitoring) ─────
-- Rows here are budget dollars that couldn't be matched to a known customer
-- or product. They still flow into totals but land under 'NEW BUSINESS'.
-- Wire this into a dbt test or alert to catch bad budget data early.
budget_orphans as (
    select
        database,
        cust_code,
        product_code,
        is_no_cust_master,
        is_no_product_master,
        sum(budget_rev)  as orphan_budget_rev,
        count(*)         as row_count
    from budget_enriched
    where is_no_cust_master or is_no_product_master
    group by 1, 2, 3, 4, 5
),

-- ── Union all grain keys from both facts ──────────────────────────────────
-- Ensures rows that exist in only one fact are not dropped by the join.
-- Dimension attributes come from sales when available; budget otherwise.
all_keys as (
    select
        reporting_segment, cust_group, database, cust_code, product_code,
        cust_name, sales_rep, product_name, product_division, prod_label,
        is_no_sales_match, is_no_cust_master, is_no_product_master
    from (
        select
            reporting_segment, cust_group, database, cust_code, product_code,
            cust_name, sales_rep, product_name, product_division, prod_label,
            false as is_no_sales_match,
            false as is_no_cust_master,       -- sales rows always have valid dim joins
            false as is_no_product_master,
            -- most recent invoice wins for prod_label (matches original Python logic)
            row_number() over (
                partition by reporting_segment, cust_group, database, cust_code, product_code
                order by year desc, month desc
            ) as rn
        from sales_enriched
    )
    where rn = 1

    union all

    -- Budget-only rows: in budget but no matching sales row.
    -- Uses IS NOT DISTINCT FROM for null-safe key comparison so rows with
    -- blank/null cust_code or product_code are correctly included.
    select distinct
        b.reporting_segment, b.cust_group, b.database, b.cust_code, b.product_code,
        b.cust_name, b.sales_rep, b.product_name, b.product_division,
        '(No Sales Match) (' || coalesce(b.product_code, 'UNKNOWN') || ')' as prod_label,
        true              as is_no_sales_match,
        b.is_no_cust_master,
        b.is_no_product_master
    from budget_enriched b
    where not exists (
        select 1 from sales_enriched s
        where s.database     is not distinct from b.database
          and s.cust_code    is not distinct from b.cust_code
          and s.product_code is not distinct from b.product_code
    )
),

-- ── Combine: join sales agg + budget agg onto the key set ─────────────────
combined as (
    select
        k.reporting_segment,
        k.cust_group,
        k.database,
        k.cust_code,
        k.cust_name,
        k.sales_rep,
        k.product_code,
        k.product_name,
        k.product_division,
        k.prod_label,
        k.is_no_sales_match,
        k.is_no_cust_master,       -- budget row with no match in stg_cust
        k.is_no_product_master,    -- budget row with no match in stg_product

        -- CY actuals
        coalesce(s.cy_cur_month,  0) as cy_cur_month,
        coalesce(s.cy_ytd,        0) as cy_ytd,
        coalesce(s.cy_cur_qtr,    0) as cy_cur_qtr,
        coalesce(s.cy_next_month, 0) as cy_next_month,
        coalesce(s.cy_whole_year, 0) as cy_whole_year,

        -- CY budget
        coalesce(b.bgt_cur_month,  0) as bgt_cur_month,
        coalesce(b.bgt_ytd,        0) as bgt_ytd,
        coalesce(b.bgt_cur_qtr,    0) as bgt_cur_qtr,
        coalesce(b.bgt_next_month, 0) as bgt_next_month,
        coalesce(b.bgt_whole_year, 0) as bgt_whole_year,

        -- PY actuals  (no PY budget exists)
        coalesce(s.py_cur_month,  0) as py_cur_month,
        coalesce(s.py_ytd,        0) as py_ytd,
        coalesce(s.py_cur_qtr,    0) as py_cur_qtr,
        coalesce(s.py_next_month, 0) as py_next_month,
        coalesce(s.py_whole_year, 0) as py_whole_year,

        -- 5-year trend: NULL when zero (Python renders as blank cell, not 0)
        nullif(coalesce(s.trend_yr_4, 0), 0) as trend_yr_4,
        nullif(coalesce(s.trend_yr_3, 0), 0) as trend_yr_3,
        nullif(coalesce(s.trend_yr_2, 0), 0) as trend_yr_2,
        nullif(coalesce(s.trend_yr_1, 0), 0) as trend_yr_1,
        nullif(coalesce(s.trend_yr_0, 0), 0) as trend_yr_0

    from       all_keys   k
    left join  sales_agg  s
           on  s.reporting_segment is not distinct from k.reporting_segment
          and  s.cust_group        is not distinct from k.cust_group
          and  s.database          is not distinct from k.database
          and  s.cust_code         is not distinct from k.cust_code
          and  s.product_code      is not distinct from k.product_code
    left join  budget_agg b
           on  b.reporting_segment is not distinct from k.reporting_segment
          and  b.cust_group        is not distinct from k.cust_group
          and  b.database          is not distinct from k.database
          and  b.cust_code         is not distinct from k.cust_code
          and  b.product_code      is not distinct from k.product_code
),

-- ── Add sort keys ─────────────────────────────────────────────────────────
-- Pre-computed so Python can order without aggregating in memory.
--   grp_cy_whole_year  → sort groups DESC within / across segments
--   cst_cy_whole_year  → sort customers DESC within a group
--   prd_cy_whole_year  → sort products DESC within a customer (= cy_whole_year)
group_totals as (
    select
        reporting_segment,
        cust_group,
        sum(cy_whole_year) as grp_cy_whole_year
    from combined
    group by 1, 2
),

customer_totals as (
    select
        reporting_segment,
        database,
        cust_code,
        sum(cy_whole_year) as cst_cy_whole_year
    from combined
    group by 1, 2, 3
)

-- ── Final output ──────────────────────────────────────────────────────────
select
    c.*,  -- includes is_no_sales_match, is_no_cust_master, is_no_product_master
    g.grp_cy_whole_year,
    t.cst_cy_whole_year,
    c.cy_whole_year as prd_cy_whole_year  -- product sort = its own CY whole year

from combined          c
join group_totals    g
  on  g.reporting_segment is not distinct from c.reporting_segment
 and  g.cust_group        is not distinct from c.cust_group
join customer_totals t
  on  t.reporting_segment is not distinct from c.reporting_segment
 and  t.database          is not distinct from c.database
 and  t.cust_code         is not distinct from c.cust_code

order by
    -- mirrors the sort order Python expects:
    -- segments alpha (NEW BUSINESS last), then groups by revenue desc,
    -- then customers by revenue desc, then products by revenue desc
    case when c.reporting_segment = 'NEW BUSINESS' then 1 else 0 end,
    c.reporting_segment,
    case when c.cust_group        = 'NEW BUSINESS' then 1 else 0 end,
    g.grp_cy_whole_year   desc,
    c.cust_group,
    t.cst_cy_whole_year   desc,
    c.cust_code,
    c.cy_whole_year       desc,
    c.product_code