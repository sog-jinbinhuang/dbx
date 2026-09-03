-- models/marts/finance/fct_production_opex.sql

with params as (
    select
        year(current_date())     as cy,
        year(current_date()) - 1 as py,
        month(current_date())    as cur_month,
        quarter(current_date())  as cur_qtr
),

process_accounts as (
    select * from {{ ref('production_process_accounts') }}
),

gl_base as (
    select
        gl.source_database                          as entity,
        gl.posting_year,
        gl.posting_period,
        gl.fiscal_quarter,
        pa.category,
        pa.process,
        pa.type,
        pa.account_num,
        gl.chempax_account_description_en           as account_en,
        signed_amount_usd
    from {{ ref('fct_global_gl') }} gl
    inner join process_accounts pa
        on  replace(gl.chempax_account_num, '-', '') = replace(pa.account_num, '-', '')
    cross join params p
    where coalesce(gl.posting_period, 0) between 1 and 12
      and gl.posting_year in (p.cy, p.py)
),

pivoted as (
    select
        a.entity,
        a.category,
        a.process,
        a.type,
        a.account_num,
        a.account_en,
        p.cy,
        p.py,
        p.cur_month,
        p.cur_qtr,

        -- =================== CY periods ===================
        sum(case when a.posting_year = p.cy and a.posting_period  = p.cur_month             then a.signed_amount_usd end) as cy_cur_month,
        sum(case when a.posting_year = p.cy and a.posting_period <= p.cur_month             then a.signed_amount_usd end) as cy_ytd,
        sum(case when a.posting_year = p.cy and a.fiscal_quarter  = concat('Q', p.cur_qtr)       then a.signed_amount_usd end) as cy_cur_qtr,

        -- =================== PY periods ===================
        sum(case when a.posting_year = p.py and a.posting_period  = p.cur_month             then a.signed_amount_usd end) as py_cur_month,
        sum(case when a.posting_year = p.py and a.posting_period <= p.cur_month             then a.signed_amount_usd end) as py_ytd,
        sum(case when a.posting_year = p.py and a.fiscal_quarter  = concat('Q', p.cur_qtr)       then a.signed_amount_usd end) as py_cur_qtr,

        -- =================== variance ===================
        sum(case when a.posting_year = p.cy and a.posting_period  = p.cur_month then a.signed_amount_usd end) -
        sum(case when a.posting_year = p.py and a.posting_period  = p.cur_month then a.signed_amount_usd end) as var_cur_month,

        sum(case when a.posting_year = p.cy and a.posting_period <= p.cur_month then a.signed_amount_usd end) -
        sum(case when a.posting_year = p.py and a.posting_period <= p.cur_month then a.signed_amount_usd end) as var_ytd,

        sum(case when a.posting_year = p.cy and a.fiscal_quarter = concat('Q', p.cur_qtr) then a.signed_amount_usd end) -
        sum(case when a.posting_year = p.py and a.fiscal_quarter = concat('Q', p.cur_qtr) then a.signed_amount_usd end) as var_cur_qtr,

        -- =================== CY monthly ===================
        sum(case when a.posting_year = p.cy and a.posting_period =  1 then a.signed_amount_usd end) as cy_m01,
        sum(case when a.posting_year = p.cy and a.posting_period =  2 then a.signed_amount_usd end) as cy_m02,
        sum(case when a.posting_year = p.cy and a.posting_period =  3 then a.signed_amount_usd end) as cy_m03,
        sum(case when a.posting_year = p.cy and a.posting_period =  4 then a.signed_amount_usd end) as cy_m04,
        sum(case when a.posting_year = p.cy and a.posting_period =  5 then a.signed_amount_usd end) as cy_m05,
        sum(case when a.posting_year = p.cy and a.posting_period =  6 then a.signed_amount_usd end) as cy_m06,
        sum(case when a.posting_year = p.cy and a.posting_period =  7 then a.signed_amount_usd end) as cy_m07,
        sum(case when a.posting_year = p.cy and a.posting_period =  8 then a.signed_amount_usd end) as cy_m08,
        sum(case when a.posting_year = p.cy and a.posting_period =  9 then a.signed_amount_usd end) as cy_m09,
        sum(case when a.posting_year = p.cy and a.posting_period = 10 then a.signed_amount_usd end) as cy_m10,
        sum(case when a.posting_year = p.cy and a.posting_period = 11 then a.signed_amount_usd end) as cy_m11,
        sum(case when a.posting_year = p.cy and a.posting_period = 12 then a.signed_amount_usd end) as cy_m12

    from gl_base a
    cross join params p
    group by
        a.entity,
        a.category,
        a.process,
        a.type,
        a.account_num,
        a.account_en,
        p.cy,
        p.py,
        p.cur_month,
        p.cur_qtr
),

-- sort key by category + process CY YTD spend
category_totals as (
    select
        entity,
        category,
        process,
        sum(cy_ytd) as process_cy_ytd
    from pivoted
    group by 1, 2, 3
)

select
    p.*,
    c.process_cy_ytd as process_sort_key
from pivoted p
left join category_totals c
    on  p.entity   = c.entity
    and p.category = c.category
    and p.process  = c.process
order by
    p.entity,
    p.category,
    p.process,
    p.type