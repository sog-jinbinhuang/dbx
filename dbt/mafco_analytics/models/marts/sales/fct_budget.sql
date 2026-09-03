with months as (
    select 1  as month_num union all
    select 2  union all
    select 3  union all
    select 4  union all
    select 5  union all
    select 6  union all
    select 7  union all
    select 8  union all
    select 9  union all
    select 10 union all
    select 11 union all
    select 12
),

-- unpivot monthly qty/rev columns into rows
unpivoted as (
    select
        b.sales_agent_2,
        b.cust_group,
        b.cust_name,
        b.cust_code,
        b.customer_class,
        b.industry_code,
        b.division,
        b.database,
        b.division_cust_code_product_code,
        b.segment,
        b.seg_custgrp,
        b.product_class,
        b.product_name,
        b.year,
        b.product_code,
        b.price,
        m.month_num,
        case m.month_num
            when 1  then b.qty_1  when 2  then b.qty_2  when 3  then b.qty_3
            when 4  then b.qty_4  when 5  then b.qty_5  when 6  then b.qty_6
            when 7  then b.qty_7  when 8  then b.qty_8  when 9  then b.qty_9
            when 10 then b.qty_10 when 11 then b.qty_11 when 12 then b.qty_12
        end as qty,
        case m.month_num
            when 1  then b.rev_1  when 2  then b.rev_2  when 3  then b.rev_3
            when 4  then b.rev_4  when 5  then b.rev_5  when 6  then b.rev_6
            when 7  then b.rev_7  when 8  then b.rev_8  when 9  then b.rev_9
            when 10 then b.rev_10 when 11 then b.rev_11 when 12 then b.rev_12
        end as rev
    from {{ ref('budget') }} as b
    cross join months as m
),

-- standardize database names and build composite keys
final as (
    select
        case
            when upper(trim(database)) = 'USA'   then 'US'
            when upper(trim(database)) = 'WF HK' then 'WEIFENG'
            else upper(trim(database))
        end || '-' || upper(nullif(trim(cust_code), ''))    as cust_uid,

        case
            when upper(trim(database)) = 'USA'   then 'US'
            when upper(trim(database)) = 'WF HK' then 'WEIFENG'
            else upper(trim(database))
        end || '-' || upper(nullif(trim(product_code), '')) as product_uid,

        make_date(year, month_num, 1)                   as date,

        case
            when upper(trim(database)) = 'USA'   then 'US'
            when upper(trim(database)) = 'WF HK' then 'WEIFENG'
            else upper(trim(database))
        end                                                  as database,

        year,
        month_num,
        cust_code,
        product_code,
        rev                             as budget_rev,
        qty                             as budget_qty,
        price                           as budget_price,
        sales_agent_2,
        cust_group,
        cust_name,
        customer_class,
        industry_code,
        division,
        segment,
        product_class,
        product_name,
        upper(trim(sales_agent_2))      as sales_rep_name,
        upper(trim(segment))            as segment_name,
        upper(trim(cust_group))         as cust_group_name
    from unpivoted
)

select * from final