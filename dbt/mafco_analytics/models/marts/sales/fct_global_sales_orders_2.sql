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

joined as (
    select
        so.*,
        c.product_key,
        c.product_segment
    from sales_orders  so
    left join prod    c
        on  so.database  = c.source_database
        and so.product_code = c.product_code
)

select * from joined