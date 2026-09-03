with sales_orders as (
    select * from {{ ref('fct_global_sales_orders') }}
),

prod as (
    select
        source_database,
        product_code,
        product_key,
        product_segment
    from {{ ref('stg_product') }}
),

dterm as (
    select
        database,
        invoice_num
    from {{ ref('dterm') }}
),

joined as (
    select
        so.*,
        c.product_key,
        c.product_segment,
        dt.invoice_num is null as is_delivered,

        -- revenue in USD using 12-month prior rate
        case
            when upper(so.invoice_currency) = 'USD' then so.revenue
            when so.database = 'CHINA'   and upper(so.invoice_currency) = 'RMB'  then so.ext_price_local_currency / nullif(exch_c.rate, 0)
            when so.database = 'EVD'     and upper(so.invoice_currency) = 'EURO' then so.ext_price_local_currency / nullif(exch_e.rate, 0)
            else so.revenue
        end as revenue_usd_12m_rate,

        -- cogs in USD using 12-month prior rate
        case
            when upper(so.invoice_currency) = 'USD' then so.cogs
            when so.database = 'CHINA'   and upper(so.invoice_currency) = 'RMB'  then so.ext_cost_local_currency / nullif(exch_c.rate, 0)
            when so.database = 'EVD'     and upper(so.invoice_currency) = 'EURO' then so.ext_cost_local_currency / nullif(exch_e.rate, 0)
            else so.cogs
        end as cogs_usd_12m_rate,

        -- 12-month prior rate used
        case
            when upper(so.invoice_currency) = 'USD' then null
            when so.database = 'CHINA'   and upper(so.invoice_currency) = 'RMB'  then exch_c.rate
            when so.database = 'EVD'     and upper(so.invoice_currency) = 'EURO' then exch_e.rate
            else null
        end as usd_12m_rate_used,

        -- current period rate
        case
            when upper(so.invoice_currency) = 'USD' then null
            when so.database = 'CHINA'   and upper(so.invoice_currency) = 'RMB'  then exch_c_curr.rate
            when so.database = 'EVD'     and upper(so.invoice_currency) = 'EURO' then exch_e_curr.rate
            else null
        end as usd_current_rate,

        -- revenue in USD using budget rate
        case
            when upper(so.invoice_currency) = 'USD' then so.revenue
            when upper(so.invoice_currency) = 'RMB'  then so.ext_price_local_currency / 7.1429
            when upper(so.invoice_currency) = 'EURO' then so.ext_price_local_currency / 0.8547
            else so.revenue
        end as revenue_usd_budget_rate,

        -- cogs in USD using budget rate
        case
            when upper(so.invoice_currency) = 'USD' then so.cogs
            when upper(so.invoice_currency) = 'RMB'  then so.ext_cost_local_currency / 7.1429
            when upper(so.invoice_currency) = 'EURO' then so.ext_cost_local_currency / 0.8547
            else so.cogs
        end as cogs_usd_budget_rate,

        -- budget rate used
        case
            when upper(so.invoice_currency) = 'USD'  then null
            when upper(so.invoice_currency) = 'RMB'  then 7.1429
            when upper(so.invoice_currency) = 'EURO' then 0.8547
            else null
        end as usd_budget_rate,

        -- price per kg in USD using 12-month prior rate
        case
            when upper(so.invoice_currency) = 'USD' then so.price_per_kg_in_usd
            when so.database = 'CHINA'   and upper(so.invoice_currency) = 'RMB'  then so.price_per_kg_local_currency / nullif(exch_c.rate, 0)
            when so.database = 'EVD'     and upper(so.invoice_currency) = 'EURO' then so.price_per_kg_local_currency / nullif(exch_e.rate, 0)
            else so.price_per_kg_in_usd
        end as price_per_kg_usd_12m_rate,

        -- price per kg in USD using budget rate
        case
            when upper(so.invoice_currency) = 'USD' then so.price_per_kg_in_usd
            when upper(so.invoice_currency) = 'RMB'  then so.price_per_kg_local_currency / 7.1429
            when upper(so.invoice_currency) = 'EURO' then so.price_per_kg_local_currency / 0.8547
            else so.price_per_kg_in_usd
        end as price_per_kg_usd_budget_rate,

        -- cost per kg in USD using budget rate
        case
            when upper(so.invoice_currency) = 'USD' then so.cost_per_kg_in_usd
            when upper(so.invoice_currency) = 'RMB'  then so.cost_per_kg_local_currency / 7.1429
            when upper(so.invoice_currency) = 'EURO' then so.cost_per_kg_local_currency / 0.8547
            else so.cost_per_kg_in_usd
        end as cost_per_kg_usd_budget_rate

    from sales_orders so
    left join prod c
        on  so.database     = c.source_database
        and so.product_code = c.product_code
    left join dterm dt
        on  so.database    = dt.database
        and so.invoice_num = dt.invoice_num
    -- 12-month prior rate joins
    left join {{ ref('exch_rate_china') }} as exch_c
        on  so.database                = 'CHINA'
        and upper(so.invoice_currency) = 'RMB'
        and exch_c.period              = CAST(date_format(dateadd(month, -12, to_date(CAST(so.year_period AS STRING), 'yyyyMM')), 'yyyyMM') AS INT)
    left join {{ ref('exch_rate_euro') }} as exch_e
        on  so.database                = 'EVD'
        and upper(so.invoice_currency) = 'EURO'
        and exch_e.period              = CAST(date_format(dateadd(month, -12, to_date(CAST(so.year_period AS STRING), 'yyyyMM')), 'yyyyMM') AS INT)
    -- current period rate joins
    left join {{ ref('exch_rate_china') }} as exch_c_curr
        on  so.database                = 'CHINA'
        and upper(so.invoice_currency) = 'RMB'
        and exch_c_curr.period         = CAST(so.year_period AS INT)
    left join {{ ref('exch_rate_euro') }} as exch_e_curr
        on  so.database                = 'EVD'
        and upper(so.invoice_currency) = 'EURO'
        and exch_e_curr.period         = CAST(so.year_period AS INT)
)

select * from joined